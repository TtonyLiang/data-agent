"""登录注册 API。"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.models.user import LoginRequest, LoginResponse, PublicUser, RegisterRequest
from app.services.user_service import AuthError, PermissionDenied, get_user_service

router = APIRouter()


@router.post("/register")
async def register(payload: RegisterRequest):
    """开放注册普通用户。新用户默认没有智能体权限。"""
    try:
        user = await get_user_service().register_user(
            payload.username,
            payload.password,
            payload.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user": user.model_dump(), "message": "注册成功"}


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest):
    """用户名密码登录，返回 JWT access token。"""
    try:
        token, user = await get_user_service().authenticate(payload.username, payload.password)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return LoginResponse(access_token=token, user=user)


@router.post("/logout")
async def logout():
    """JWT 第一版由前端清理 token，后端保持无状态。"""
    return {"message": "已退出"}


@router.get("/me", response_model=PublicUser)
async def me(current_user: PublicUser = Depends(get_current_user)):
    """查询当前登录用户。"""
    return current_user
