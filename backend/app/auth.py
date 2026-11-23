from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import HTTPException, Request, Response, status

from .config import get_settings

SESSION_COOKIE_NAME = "radar_session"
SESSION_TTL_SECONDS = 30 * 24 * 3600  # 30 days


def _sign_payload(payload: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def create_session_token() -> str:
    settings = get_settings()
    exp = int(time.time()) + SESSION_TTL_SECONDS
    payload = f"radar:{exp}"
    sig = _sign_payload(payload, settings.resolved_session_secret())
    return f"{payload}.{sig}"


def verify_session_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    settings = get_settings()
    try:
        payload, sig = token.rsplit(".", 1)
        expected = _sign_payload(payload, settings.resolved_session_secret())
        if not hmac.compare_digest(sig, expected):
            return False
        _, exp_str = payload.split(":", 1)
        return int(exp_str) > int(time.time())
    except Exception:
        return False


def is_authenticated(request: Request) -> bool:
    settings = get_settings()
    if not settings.app_access_password.strip():
        return True
    token = request.cookies.get(SESSION_COOKIE_NAME) or request.headers.get("X-Access-Token")
    return verify_session_token(token)


def require_auth(request: Request) -> None:
    if not is_authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请输入访问密码登录",
        )


def set_session_cookie(request: Request, response: Response, token: str) -> None:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    is_https = request.url.scheme == "https" or forwarded_proto == "https"
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=is_https,
        max_age=SESSION_TTL_SECONDS,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
