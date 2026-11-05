
from fastapi import APIRouter, HTTPException, Depends

import app.database as database

from ..schemas import LoginRequest
from ..security import verify_password, create_access_token
from ..dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(payload: LoginRequest):

    db = database.db

    if db is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection is not available"
        )

    user = await db.users.find_one({
        "username": payload.username
    })

    if not user or not verify_password(
        payload.password,
        user["password_hash"]
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    if not user.get("is_active", True):
        raise HTTPException(
            status_code=403,
            detail="Account disabled"
        )

    token = create_access_token({
        "sub": str(user["_id"]),
        "role": user["role"]
    })

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(user["_id"]),
            "username": user["username"],
            "full_name": user.get("full_name", ""),
            "role": user["role"],
        },
    }


@router.get("/me")
async def me(user=Depends(get_current_user)):
    return {
        "id": str(user["_id"]),
        "username": user["username"],
        "full_name": user.get("full_name", ""),
        "role": user["role"],
    }
