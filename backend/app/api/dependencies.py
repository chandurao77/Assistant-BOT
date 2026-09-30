"""Shared FastAPI dependencies: authentication, etc."""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status

from app.config import Settings, get_settings


async def verify_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    """
    Validates the X-API-Key header when API_KEY is configured in settings.
    If API_KEY is empty (default), authentication is disabled — safe for local dev.

    Also accepts a valid JWT Bearer token from an admin user, so the
    frontend sync button works without exposing the API key to the browser.
    """
    if not settings.api_key:
        return  # Auth disabled — no key configured
    if x_api_key == settings.api_key:
        return  # Valid API key

    # Fallback: accept JWT Bearer token from admin users only
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        auth_service = getattr(request.app.state, "auth", None)
        if auth_service:
            payload = auth_service.decode_token(token)
            if payload and payload.get("role") == "admin":
                return  # Valid admin JWT accepted

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key. Provide a valid key in the X-API-Key header.",
        headers={"WWW-Authenticate": "ApiKey"},
    )


async def get_current_user(request: Request) -> dict:
    """
    Extract user from JWT Bearer token in the Authorization header.
    Returns user dict ``{"id", "name", "email"}`` or raises 401.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header. Use: Bearer <token>",
        )
    token = auth_header[7:]  # strip "Bearer "
    auth_service = request.app.state.auth
    payload = auth_service.decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token. Please log in again.",
        )
    return {
        "id": payload["sub"],
        "name": payload["name"],
        "email": payload["email"],
        "role": payload.get("role", "user"),
        "allowed_spaces": payload.get("allowed_spaces", []),
    }


async def get_optional_user(request: Request) -> dict | None:
    """
    Same as get_current_user but returns None instead of raising 401
    when no token is provided. Used for endpoints that work with or without auth.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    auth_service = request.app.state.auth
    payload = auth_service.decode_token(token)
    if not payload:
        return None
    return {
        "id": payload["sub"],
        "name": payload["name"],
        "email": payload["email"],
        "role": payload.get("role", "user"),
        "allowed_spaces": payload.get("allowed_spaces", []),
    }


async def require_admin(request: Request) -> dict:
    """Require the caller to be an admin. Returns user dict or raises 403."""
    user = await get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return user


def require_space_access(space_keys: list[str]):
    """Factory: returns a dependency that checks user has access to given spaces."""
    async def _check(request: Request) -> dict:
        user = await get_current_user(request)
        allowed = user.get("allowed_spaces", [])
        if not allowed:  # empty = access to all spaces
            return user
        denied = [k for k in space_keys if k not in allowed]
        if denied:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to space(s): {', '.join(denied)}",
            )
        return user
    return _check
