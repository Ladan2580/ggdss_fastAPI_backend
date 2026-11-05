from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone
from ..database import db
from ..schemas import ScoreBatch
from ..dependencies import require_roles
from ..helpers import oid, audit

router = APIRouter(prefix="/scores", tags=["scores"])

ALLOWED = ("super_admin", "school_admin", "teacher")


async def _authorised_for(actor: dict, session_id: str, class_id: str, subject_id: str, arm_id: str | None):
    if actor["role"] in ("super_admin", "school_admin"):
        return
    flt = {
        "teacher_id": actor["_id"],
        "session_id": oid(session_id),
        "class_id": oid(class_id),
        "subject_id": oid(subject_id),
    }
    if arm_id:
        flt["arm_id"] = oid(arm_id)
    if not await db.assignments.find_one(flt):
        raise HTTPException(status_code=403, detail="Not assigned to this subject/class")


@router.get("")
async def fetch_scores(
    session_id: str,
    class_id: str,
    subject_id: str,
    arm_id: str | None = None,
    actor=Depends(require_roles(*ALLOWED)),
):
    await _authorised_for(actor, session_id, class_id, subject_id, arm_id)

    s_flt = {"status": "active", "class_id": oid(class_id)}
    if arm_id:
        s_flt["arm_id"] = oid(arm_id)
    students = await db.students.find(s_flt).sort("full_name", 1).to_list(1000)
    score_flt = {
        "session_id": oid(session_id),
        "class_id": oid(class_id),
        "subject_id": oid(subject_id),
    }
    if arm_id:
        score_flt["arm_id"] = oid(arm_id)
    scores = await db.subject_results.find(score_flt).to_list(1000)
    score_map = {str(s["student_id"]): s for s in scores}

    items = []
    for s in students:
        r = score_map.get(str(s["_id"]), {})
        items.append({
            "student_id": str(s["_id"]),
            "admission_no": s["admission_no"],
            "full_name": s["full_name"],
            "assignment": r.get("assignment"),
            "first_ca": r.get("first_ca"),
            "second_ca": r.get("second_ca"),
            "exam": r.get("exam"),
            "status": r.get("status", "draft"),
        })
    return {"items": items}


async def _save(actor: dict, payload: ScoreBatch, submit: bool):
    await _authorised_for(actor, payload.session_id, payload.class_id, payload.subject_id, payload.arm_id)
    now = datetime.now(timezone.utc)
    for item in payload.items:
        flt = {
            "session_id": oid(payload.session_id),
            "class_id": oid(payload.class_id),
            "subject_id": oid(payload.subject_id),
            "student_id": oid(item.student_id),
            "arm_id": oid(payload.arm_id) if payload.arm_id else None,
        }
        complete = all([item.assignment is not None, item.first_ca is not None, item.second_ca is not None, item.exam is not None])
        status = "submitted" if (submit and complete) else "draft"
        await db.subject_results.update_one(
            flt,
            {
                "$set": {
                    "assignment": item.assignment,
                    "first_ca": item.first_ca,
                    "second_ca": item.second_ca,
                    "exam": item.exam,
                    "status": status,
                    "updated_by": actor["_id"],
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
    await audit(db, actor, "scores.submit" if submit else "scores.draft", {
        "session_id": payload.session_id,
        "class_id": payload.class_id,
        "subject_id": payload.subject_id,
        "count": len(payload.items),
    })
    return {"ok": True}


@router.post("")
async def save_draft(payload: ScoreBatch, actor=Depends(require_roles(*ALLOWED))):
    return await _save(actor, payload, submit=False)


@router.post("/submit")
async def submit_scores(payload: ScoreBatch, actor=Depends(require_roles(*ALLOWED))):
    return await _save(actor, payload, submit=True)