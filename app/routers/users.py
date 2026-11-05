
from fastapi import APIRouter, Depends, HTTPException

import app.database as database

from ..schemas import UserCreate, UserRoleUpdate
from ..security import hash_password
from ..dependencies import require_roles
from ..helpers import oid, audit

router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
async def list_users(_=Depends(require_roles("super_admin"))):
    db = database.db

    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    users = await db.users.find({}).to_list(500)

    return [
        {
            "id": str(u["_id"]),
            "username": u["username"],
            "full_name": u.get("full_name", ""),
            "role": u["role"],
            "is_active": u.get("is_active", True)
        }
        for u in users
    ]


@router.post("")
async def create_user(
    payload: UserCreate,
    # actor=Depends(require_roles("super_admin"))
):
    db = database.db

    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    if await db.users.find_one({"username": payload.username}):
        raise HTTPException(
            status_code=400,
            detail="Username already exists"
        )

    res = await db.users.insert_one({
        "username": payload.username,
        "full_name": payload.full_name,
        "password_hash": hash_password(payload.password),
        "role": payload.role,
        "is_active": True,
    })

    await audit(
        db,
        actor,
        "user.create",
        {
            "username": payload.username,
            "role": payload.role
        }
    )

    return {"id": str(res.inserted_id)}


@router.put("/{user_id}/role")
async def update_role(
    user_id: str,
    payload: UserRoleUpdate,
    actor=Depends(require_roles("super_admin"))
):
    db = database.db

    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    res = await db.users.update_one(
        {"_id": oid(user_id)},
        {"$set": {"role": payload.role}}
    )

    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    await audit(
        db,
        actor,
        "user.role_change",
        {
            "user_id": user_id,
            "role": payload.role
        }
    )

    return {"ok": True}


@router.post("/{user_id}/deactivate")
async def deactivate(
    user_id: str,
    actor=Depends(require_roles("super_admin"))
):
    db = database.db

    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    res = await db.users.update_one(
        {"_id": oid(user_id)},
        {"$set": {"is_active": False}}
    )

    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    await audit(
        db,
        actor,
        "user.deactivate",
        {"user_id": user_id}
    )

    return {"ok": True}


@router.get("/audit-logs")
async def list_audit_logs(
    limit: int = 50,
    _=Depends(require_roles("super_admin", "school_admin"))
):
    db = database.db

    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    limit = max(1, min(limit, 500))

    logs = await db.audit_logs.find({}).sort(
        "created_at", -1
    ).limit(limit).to_list(limit)

    return [
        {
            "id": str(log["_id"]),
            "actor_username": log.get("actor_username", ""),
            "action": log.get("action", ""),
            "details": log.get("details", {}),
            "created_at": (
                log.get("created_at").isoformat()
                if log.get("created_at")
                else None
            ),
        }
        for log in logs
    ]
