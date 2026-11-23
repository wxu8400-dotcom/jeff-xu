from __future__ import annotations

import hmac

from fastapi import APIRouter, HTTPException, Request, Response, status

from ..auth import (
    clear_session_cookie,
    create_session_token,
    is_authenticated,
    set_session_cookie,
)
from ..config import get_settings
from ..schemas import AuthStatusOut, LoginRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status", response_model=AuthStatusOut)
def auth_status(request: Request) -> AuthStatusOut:
    settings = get_settings()
    return AuthStatusOut(
        password_required=bool(settings.app_access_password.strip()),
        authenticated=is_authenticated(request),
    )


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, str | bool]:
    settings = get_settings()
    expected = settings.app_access_password.strip()
    if not expected:
        return {"ok": True, "token": ""}
    if not hmac.compare_digest(payload.password.strip(), expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="访问密码错误，请重试",
        )
    token = create_session_token()
    set_session_cookie(request, response, token)
    return {"ok": True, "token": token}


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    clear_session_cookie(response)
    return {"ok": True}
