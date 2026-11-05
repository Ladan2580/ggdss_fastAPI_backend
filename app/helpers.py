from typing import Any
from bson import ObjectId
from fastapi import HTTPException


def oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid identifier")


def str_id(doc: dict) -> dict:
    if not doc:
        return doc
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    for k in ("session_id", "class_id", "arm_id", "subject_id", "student_id", "teacher_id"):
        if doc.get(k) is not None:
            doc[k] = str(doc[k])
    return doc


def grade_for(total: int, rules: list[dict]) -> tuple[str, str]:
    for r in rules:
        if r["min"] <= total <= r["max"]:
            return r["grade"], r["remark"]
    return "F", "Fail"


def competition_rank(sorted_scores: list[int]) -> list[int]:
    """Competition ranking: 1st, 2nd, 2nd, 4th."""
    ranks = []
    for i, s in enumerate(sorted_scores):
        if i > 0 and s == sorted_scores[i - 1]:
            ranks.append(ranks[-1])
        else:
            ranks.append(i + 1)
    return ranks


async def audit(db, actor: dict, action: str, details: Any = None):
    from datetime import datetime, timezone
    await db.audit_logs.insert_one({
        "actor_id": actor["_id"],
        "actor_username": actor["username"],
        "action": action,
        "details": details or {},
        "created_at": datetime.now(timezone.utc),
    })