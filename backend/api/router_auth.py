import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.api.schemas import (
    ApiResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from backend.core.exceptions import UnauthorizedError, ValidationError
from backend.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from backend.database.session import get_db
from backend.models.user import User

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.post("/register", response_model=ApiResponse)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(User).where((User.username == body.username) | (User.email == body.email))
    )
    if existing.scalar_one_or_none():
        raise ValidationError(detail={"username": "用户名或邮箱已被注册"})

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    await db.flush()

    return ApiResponse(data=UserResponse.model_validate(user))


@router.post("/login", response_model=ApiResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
        raise UnauthorizedError()

    if not user.is_active:
        raise UnauthorizedError()

    token_data = {"sub": str(user.id), "username": user.username}
    return ApiResponse(
        data=TokenResponse(
            access_token=create_access_token(token_data),
            refresh_token=create_refresh_token(token_data),
            expires_in=60,  # minutes
        )
    )


@router.get("/me", response_model=ApiResponse)
async def me(current_user: User = Depends(get_current_user)):
    return ApiResponse(data=UserResponse.model_validate(current_user))
