from fastapi import APIRouter, Depends, HTTPException
from ..database import db
from ..schemas import SubjectCreate, AssignmentCreate
from ..dependencies import require_roles
from ..helpers import str_id, oid, audit

router = APIRouter(tags=["subjects"])
ADMIN_ROLES = ("super_admin", "school_admin")


@router.get("/subjects")
async def list_subjects(_=Depends(require_roles(*ADMIN_ROLES, "teacher"))):
    docs = await db.subjects.find({}).sort("name", 1).to_list(500)
    return [str_id(d) for d in docs]


@router.post("/subjects")
async def create_subject(payload: SubjectCreate, actor=Depends(require_roles(*ADMIN_ROLES))):
    if await db.subjects.find_one({"name": payload.name}):
        raise HTTPException(status_code=400, detail="Subject already exists")
    res = await db.subjects.insert_one(payload.model_dump())
    await audit(db, actor, "subject.create", payload.model_dump())
    return {"id": str(res.inserted_id)}


@router.post("/subjects/assign")
async def assign_subject(payload: AssignmentCreate, actor=Depends(require_roles(*ADMIN_ROLES))):
    doc = payload.model_dump()
    doc["teacher_id"] = oid(doc["teacher_id"])
    doc["session_id"] = oid(doc["session_id"])
    doc["class_id"] = oid(doc["class_id"])
    doc["subject_id"] = oid(doc["subject_id"])
    if doc.get("arm_id"):
        doc["arm_id"] = oid(doc["arm_id"])
    res = await db.assignments.insert_one(doc)
    await audit(db, actor, "assignment.create", payload.model_dump())
    return {"id": str(res.inserted_id)}


@router.get("/subjects/assignments")
async def list_assignments(
    teacher_id: str | None = None,
    session_id: str | None = None,
    class_id: str | None = None,
    _=Depends(require_roles(*ADMIN_ROLES, "teacher")),
):
    flt = {}
    if teacher_id:
        flt["teacher_id"] = oid(teacher_id)
    if session_id:
        flt["session_id"] = oid(session_id)
    if class_id:
        flt["class_id"] = oid(class_id)
    docs = await db.assignments.find(flt).to_list(500)

    teacher_map = {str(u["_id"]): u.get("full_name", u["username"]) for u in await db.users.find({}).to_list(500)}
    subject_map = {str(s["_id"]): s["name"] for s in await db.subjects.find({}).to_list(500)}
    class_map = {str(c["_id"]): c["name"] for c in await db.classes.find({}).to_list(200)}
    arm_map = {str(a["_id"]): a["name"] for a in await db.arms.find({}).to_list(200)}
    session_map = {str(s["_id"]): f"{s['name']} — {s['term']}" for s in await db.sessions.find({}).to_list(200)}

    out = []
    for a in docs:
        d = str_id(a)
        d["teacher_name"] = teacher_map.get(d["teacher_id"], "")
        d["subject_name"] = subject_map.get(d["subject_id"], "")
        d["class_name"] = class_map.get(d["class_id"], "")
        d["arm_name"] = arm_map.get(d.get("arm_id") or "", "")
        full = session_map.get(d["session_id"], "")
        if " — " in full:
            d["session_name"], d["term"] = full.split(" — ", 1)
        else:
            d["session_name"], d["term"] = full, ""
        out.append(d)
    return out