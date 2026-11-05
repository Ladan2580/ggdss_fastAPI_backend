from fastapi import APIRouter, Depends, HTTPException
from ..database import db
from ..schemas import SessionCreate, ClassCreate, ArmCreate
from ..dependencies import require_roles
from ..helpers import str_id, audit

router = APIRouter(prefix="/academic", tags=["academic"])
ADMIN_ROLES = ("super_admin", "school_admin")


@router.get("/sessions")
async def list_sessions(_=Depends(require_roles(*ADMIN_ROLES, "teacher"))):
    docs = await db.sessions.find({}).sort([("name", -1), ("term", 1)]).to_list(200)
    return [str_id(d) for d in docs]


@router.post("/sessions")
async def create_session(payload: SessionCreate, actor=Depends(require_roles(*ADMIN_ROLES))):
    if await db.sessions.find_one({"name": payload.name, "term": payload.term}):
        raise HTTPException(status_code=400, detail="Session/term already exists")
    if payload.is_current:
        await db.sessions.update_many({}, {"$set": {"is_current": False}})
    res = await db.sessions.insert_one(payload.model_dump())
    await audit(db, actor, "session.create", payload.model_dump())
    return {"id": str(res.inserted_id)}


@router.get("/classes")
async def list_classes(_=Depends(require_roles(*ADMIN_ROLES, "teacher"))):
    docs = await db.classes.find({}).sort("name", 1).to_list(200)
    return [str_id(d) for d in docs]


@router.post("/classes")
async def create_class(payload: ClassCreate, actor=Depends(require_roles(*ADMIN_ROLES))):
    if await db.classes.find_one({"name": payload.name}):
        raise HTTPException(status_code=400, detail="Class already exists")
    res = await db.classes.insert_one(payload.model_dump())
    await audit(db, actor, "class.create", payload.model_dump())
    return {"id": str(res.inserted_id)}


@router.get("/arms")
async def list_arms(_=Depends(require_roles(*ADMIN_ROLES, "teacher"))):
    docs = await db.arms.find({}).sort("name", 1).to_list(200)
    return [str_id(d) for d in docs]


@router.post("/arms")
async def create_arm(payload: ArmCreate, actor=Depends(require_roles(*ADMIN_ROLES))):
    if await db.arms.find_one({"name": payload.name}):
        raise HTTPException(status_code=400, detail="Arm already exists")
    res = await db.arms.insert_one(payload.model_dump())
    await audit(db, actor, "arm.create", payload.model_dump())
    return {"id": str(res.inserted_id)}