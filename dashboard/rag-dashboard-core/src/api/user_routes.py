from __future__ import annotations

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.app import verify_api_key

user_router = APIRouter(prefix="/users", tags=["users"])


class CreateUserRequest(BaseModel):
    username: str = Field(..., pattern=r"^[a-z0-9]{1,10}$")
    password: str = Field(..., min_length=1, max_length=128)


class UserItem(BaseModel):
    username: str


@user_router.post("", response_model=UserItem, status_code=201,
                  dependencies=[Depends(verify_api_key)])
async def create_user(body: CreateUserRequest, request: Request) -> UserItem:
    password_hash = bcrypt.hashpw(body.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.execute(
            text("SELECT 1 FROM chat_users WHERE username = :u"),
            {"u": body.username},
        )
        if result.fetchone():
            raise HTTPException(status_code=409, detail="El usuario ya existe")
        await session.execute(
            text("INSERT INTO chat_users (username, password_hash) VALUES (:u, :h)"),
            {"u": body.username, "h": password_hash},
        )
        await session.commit()
    return UserItem(username=body.username)


@user_router.get("", response_model=list[UserItem],
                 dependencies=[Depends(verify_api_key)])
async def list_users(request: Request) -> list[UserItem]:
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.execute(
            text("SELECT username FROM chat_users ORDER BY username")
        )
        rows = result.fetchall()
    return [UserItem(username=row[0]) for row in rows]


@user_router.delete("/{username}", status_code=204,
                    dependencies=[Depends(verify_api_key)])
async def delete_user(username: str, request: Request) -> None:
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.execute(
            text("DELETE FROM chat_users WHERE username = :u"),
            {"u": username},
        )
        await session.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
