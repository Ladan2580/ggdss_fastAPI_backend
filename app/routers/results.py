from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone
from bson import ObjectId
from ..database import db
from ..schemas import ApprovalAction, AssessmentSettings, GradingUpdate
from ..dependencies import require_roles
from ..helpers import oid, audit, grade_for, competition_rank

router = APIRouter(prefix="/results", tags=["results"])
ALLOWED = ("super_admin", "school_admin", "teacher")
ADMIN_ROLES = ("super_admin", "school_admin")

DEFAULT_GRADING = [
    {"grade": "A", "min": 70, "max": 100, "remark": "Excellent"},
    {"grade": "B", "min": 60, "max": 69, "remark": "Very Good"},
    {"grade": "C", "min": 50, "max": 59, "remark": "Good"},
    {"grade": "D", "min": 45, "max": 49, "remark": "Credit"},
    {"grade": "E", "min": 40, "max": 44, "remark": "Pass"},
    {"grade": "F", "min": 0, "max": 39, "remark": "Fail"},
]

DEFAULT_SETTINGS = {"assignment": 10, "first_ca": 10, "second_ca": 10, "exam": 70}


async def get_settings() -> dict:
    doc = await db.settings.find_one({"key": "assessment"})
    return {**DEFAULT_SETTINGS, **(doc.get("value") if doc else {})}


async def get_grading() -> list[dict]:
    doc = await db.settings.find_one({"key": "grading"})
    return doc.get("rules") if doc else DEFAULT_GRADING


@router.get("/settings")
async def read_settings(_=Depends(require_roles(*ALLOWED))):
    return await get_settings()


@router.put("/settings")
async def write_settings(payload: AssessmentSettings, actor=Depends(require_roles(*ADMIN_ROLES))):
    if payload.assignment + payload.first_ca + payload.second_ca + payload.exam != 100:
        raise HTTPException(status_code=400, detail="Assessment weights must sum to 100")
    await db.settings.update_one({"key": "assessment"}, {"$set": {"value": payload.model_dump()}}, upsert=True)
    await audit(db, actor, "settings.assessment", payload.model_dump())
    return {"ok": True}


@router.get("/grading")
async def read_grading(_=Depends(require_roles(*ALLOWED))):
    return await get_grading()


@router.put("/grading")
async def write_grading(payload: GradingUpdate, actor=Depends(require_roles(*ADMIN_ROLES))):
    await db.settings.update_one(
        {"key": "grading"}, {"$set": {"rules": [r.model_dump() for r in payload.rules]}}, upsert=True
    )
    await audit(db, actor, "settings.grading", {"count": len(payload.rules)})
    return {"ok": True}


async def _build_class_results(session_id: str, class_id: str, arm_id: str | None, include_unapproved: bool):
    rules = await get_grading()
    s_flt = {"status": "active", "class_id": oid(class_id)}
    if arm_id:
        s_flt["arm_id"] = oid(arm_id)
    students = await db.students.find(s_flt).sort("full_name", 1).to_list(1000)

    score_flt = {"session_id": oid(session_id), "class_id": oid(class_id)}
    if arm_id:
        score_flt["arm_id"] = oid(arm_id)
    scores = await db.subject_results.find(score_flt).to_list(5000)
    by_student: dict = {}
    for s in scores:
        by_student.setdefault(str(s["student_id"]), []).append(s)

    rows = []
    for stu in students:
        recs = by_student.get(str(stu["_id"]), [])
        # a subject result participates in aggregates only if fully complete
        complete_recs = [r for r in recs if None not in (r.get("assignment"), r.get("first_ca"), r.get("second_ca"), r.get("exam"))]
        totals = [r["assignment"] + r["first_ca"] + r["second_ca"] + r["exam"] for r in complete_recs]
        subject_statuses = [r.get("status", "draft") for r in complete_recs]
        overall_status = "draft"
        if subject_statuses and all(s == "published" for s in subject_statuses):
            overall_status = "published"
        elif subject_statuses and all(s in ("submitted", "approved", "published") for s in subject_statuses):
            overall_status = "submitted"
        if include_unapproved and subject_statuses:
            overall_status = subject_statuses[0] if len(set(subject_statuses)) == 1 else "mixed"

        total = sum(totals)
        average = round(total / len(totals), 2) if totals else 0
        passed = sum(1 for t in totals if t >= 40)
        failed = len(totals) - passed
        rows.append({
            "student_id": str(stu["_id"]),
            "admission_no": stu["admission_no"],
            "full_name": stu["full_name"],
            "subjects_offered": len(complete_recs),
            "total_score": total,
            "average": average,
            "passed": passed,
            "failed": failed,
            "status": overall_status,
            "incomplete": len(recs) != len(complete_recs),
        })

    # rankings: exclude incomplete results
    eligible = [r for r in rows if not r["incomplete"] and r["subjects_offered"] > 0]
    eligible_sorted = sorted(eligible, key=lambda r: r["total_score"], reverse=True)
    ranks = competition_rank([r["total_score"] for r in eligible_sorted])
    rank_map = {id(r): ranks[i] for i, r in enumerate(eligible_sorted)}
    for r in rows:
        r["position"] = rank_map.get(id(r))
    return rows


@router.get("/class")
async def class_results(
    session_id: str,
    class_id: str,
    arm_id: str | None = None,
    include_unapproved: bool = False,
    _=Depends(require_roles(*ALLOWED)),
):
    rows = await _build_class_results(session_id, class_id, arm_id, include_unapproved)
    return {"rows": rows}


@router.post("/approve")
async def approve(payload: ApprovalAction, actor=Depends(require_roles(*ADMIN_ROLES))):
    flt = {
        "session_id": oid(payload.session_id),
        "class_id": oid(payload.class_id),
        "student_id": oid(payload.student_id),
        "status": "submitted",
    }
    res = await db.subject_results.update_many(flt, {"$set": {"status": "approved", "approved_by": actor["_id"], "approved_at": datetime.now(timezone.utc)}})
    await audit(db, actor, "result.approve", {**payload.model_dump(), "count": res.modified_count})
    return {"ok": True, "count": res.modified_count}


@router.post("/return")
async def return_result(payload: ApprovalAction, actor=Depends(require_roles(*ADMIN_ROLES))):
    flt = {
        "session_id": oid(payload.session_id),
        "class_id": oid(payload.class_id),
        "student_id": oid(payload.student_id),
    }
    res = await db.subject_results.update_many(flt, {"$set": {"status": "draft", "returned_reason": payload.reason or "", "returned_at": datetime.now(timezone.utc)}})
    await audit(db, actor, "result.return", {**payload.model_dump(), "count": res.modified_count})
    return {"ok": True, "count": res.modified_count}


@router.post("/publish")
async def publish(payload: ApprovalAction, actor=Depends(require_roles(*ADMIN_ROLES))):
    flt = {
        "session_id": oid(payload.session_id),
        "class_id": oid(payload.class_id),
        "student_id": oid(payload.student_id),
        "status": "approved",
    }
    res = await db.subject_results.update_many(flt, {"$set": {"status": "published", "published_at": datetime.now(timezone.utc)}})
    await audit(db, actor, "result.publish", {**payload.model_dump(), "count": res.modified_count})
    return {"ok": True, "count": res.modified_count}