import csv
import io
import re
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from ..database import db
from ..schemas import StudentCreate, StudentUpdate
from ..dependencies import require_roles
from ..helpers import oid, str_id, audit

router = APIRouter(prefix="/students", tags=["students"])

ADMIN_ROLES = ("super_admin", "school_admin")


async def _next_admission_no() -> str:
    # Look for the highest numeric admission_no to generate next
    cursor = db.students.find({"admission_no": {"$regex": r"^\d+$"}}, {"admission_no": 1}).sort("admission_no", -1).limit(1)
    docs = await cursor.to_list(1)
    if not docs:
        return "0001"
    current = int(docs[0]["admission_no"])
    return str(current + 1).zfill(4)


@router.get("")
async def list_students(
    q: str | None = None,
    class_id: str | None = None,
    arm_id: str | None = None,
    gender: str | None = None,
    status: str = "active",
    page: int = 1,
    limit: int = Query(20, le=100),
    _=Depends(require_roles(*ADMIN_ROLES)),
):
    flt: dict = {}
    if q:
        flt["$or"] = [
            {"full_name": {"$regex": re.escape(q), "$options": "i"}},
            {"admission_no": {"$regex": re.escape(q)}},
        ]
    if class_id:
        flt["class_id"] = oid(class_id)
    if arm_id:
        flt["arm_id"] = oid(arm_id)
    if gender:
        flt["gender"] = gender
    if status:
        flt["status"] = status

    total = await db.students.count_documents(flt)
    cursor = db.students.find(flt).skip((page - 1) * limit).limit(limit).sort("full_name", 1)
    students = await cursor.to_list(limit)

    # enrich with class/arm names
    out = []
    class_map = {str(c["_id"]): c["name"] for c in await db.classes.find({}).to_list(200)}
    arm_map = {str(a["_id"]): a["name"] for a in await db.arms.find({}).to_list(200)}
    for s in students:
        d = str_id(s)
        d["class_name"] = class_map.get(d.get("class_id") or "", None)
        d["arm_name"] = arm_map.get(d.get("arm_id") or "", None)
        out.append(d)

    import math
    return {
        "items": out,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": max(1, math.ceil(total / limit)),
    }


@router.get("/{student_id}")
async def get_student(student_id: str, _=Depends(require_roles(*ADMIN_ROLES, "teacher"))):
    s = await db.students.find_one({"_id": oid(student_id)})
    if not s:
        raise HTTPException(status_code=404, detail="Student not found")
    return str_id(s)


@router.post("")
async def create_student(payload: StudentCreate, actor=Depends(require_roles(*ADMIN_ROLES))):
    admission_no = payload.admission_no or await _next_admission_no()
    if await db.students.find_one({"admission_no": admission_no}):
        raise HTTPException(status_code=400, detail="Admission number already exists")
    doc = payload.model_dump()
    doc["admission_no"] = admission_no
    doc["class_id"] = oid(doc["class_id"])
    if doc.get("arm_id"):
        doc["arm_id"] = oid(doc["arm_id"])
    res = await db.students.insert_one(doc)
    await audit(db, actor, "student.create", {"admission_no": admission_no})
    return {"id": str(res.inserted_id)}


@router.put("/{student_id}")
async def update_student(student_id: str, payload: StudentUpdate, actor=Depends(require_roles(*ADMIN_ROLES))):
    doc = payload.model_dump()
    doc["class_id"] = oid(doc["class_id"])
    if doc.get("arm_id"):
        doc["arm_id"] = oid(doc["arm_id"])
    if not doc.get("admission_no"):
        doc.pop("admission_no", None)
    res = await db.students.update_one({"_id": oid(student_id)}, {"$set": doc})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Student not found")
    await audit(db, actor, "student.update", {"student_id": student_id})
    return {"ok": True}


@router.post("/{student_id}/archive")
async def archive_student(student_id: str, actor=Depends(require_roles(*ADMIN_ROLES))):
    res = await db.students.update_one({"_id": oid(student_id)}, {"$set": {"status": "archived"}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Student not found")
    await audit(db, actor, "student.archive", {"student_id": student_id})
    return {"ok": True}


@router.post("/import")
async def import_students(
    file: UploadFile = File(...),
    actor=Depends(require_roles(*ADMIN_ROLES)),
):
    """CSV columns: full_name, admission_no, gender, class_name, arm_name."""
    content = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    imported = 0
    errors = []
    for idx, row in enumerate(reader, start=2):
        try:
            full_name = (row.get("full_name") or "").strip()
            admission_no = (row.get("admission_no") or "").strip()
            gender = (row.get("gender") or "female").strip().lower()
            class_name = (row.get("class_name") or "").strip()
            arm_name = (row.get("arm_name") or "").strip()
            if not full_name or not admission_no or not class_name:
                errors.append(f"Row {idx}: missing required fields")
                continue
            if gender not in ("male", "female"):
                errors.append(f"Row {idx}: invalid gender")
                continue
            if await db.students.find_one({"admission_no": admission_no}):
                errors.append(f"Row {idx}: duplicate admission_no {admission_no}")
                continue
            cls = await db.classes.find_one({"name": class_name})
            if not cls:
                errors.append(f"Row {idx}: unknown class '{class_name}'")
                continue
            arm_doc = None
            if arm_name:
                arm_doc = await db.arms.find_one({"name": arm_name})
                if not arm_doc:
                    errors.append(f"Row {idx}: unknown arm '{arm_name}'")
                    continue
            await db.students.insert_one({
                "full_name": full_name,
                "admission_no": admission_no,
                "gender": gender,
                "class_id": cls["_id"],
                "arm_id": arm_doc["_id"] if arm_doc else None,
                "status": "active",
            })
            imported += 1
        except Exception as e:
            errors.append(f"Row {idx}: {e}")
    await audit(db, actor, "student.import", {"imported": imported, "errors": len(errors)})
    return {"imported": imported, "errors": errors}