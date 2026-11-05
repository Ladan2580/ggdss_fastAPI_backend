from fastapi import APIRouter, Depends
from ..database import db
from ..dependencies import get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats")
async def stats(_=Depends(get_current_user)):
    students = await db.students.count_documents({"status": "active"})
    classes = await db.classes.count_documents({})
    subjects = await db.subjects.count_documents({})
    pending = await db.subject_results.count_documents({"status": "submitted"})
    published = await db.subject_results.count_documents({"status": "published"})
    session = await db.sessions.find_one({"is_current": True})
    return {
        "students": students,
        "classes": classes,
        "subjects": subjects,
        "pending_approvals": pending,
        "published_results": published,
        "current_session": {"name": session["name"]} if session else None,
        "current_term": {"name": session["term"]} if session else None,
    }