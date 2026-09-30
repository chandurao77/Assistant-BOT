"""Authentication endpoints — register, login, current user."""
from __future__ import annotations

import json as _json
import time
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from app.api.dependencies import get_current_user as _get_user, require_admin
from app.config import get_settings
from app.services.oidc import OIDCProvider

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class AuthResponse(BaseModel):
    token: str
    user: dict


class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    role: str = "user"
    allowed_spaces: list[str] = []


class UpdateRoleRequest(BaseModel):
    role: str = Field(pattern="^(user|admin)$")
    allowed_spaces: list[str] = []


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, request: Request):
    auth = request.app.state.auth
    user = await auth.register(body.name, body.email, body.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )
    token = auth.create_token(user["id"], user["email"], user["name"], user.get("role", "user"), user.get("allowed_spaces", []))
    return {"token": token, "user": user}


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, request: Request):
    auth = request.app.state.auth
    user = await auth.authenticate(body.email, body.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    token = auth.create_token(user["id"], user["email"], user["name"], user.get("role", "user"), user.get("allowed_spaces", []))
    return {"token": token, "user": user}


@router.get("/me", response_model=UserResponse)
async def get_current_user(request: Request):
    user = await _get_user(request)
    return user


@router.put("/users/{user_id}/role", response_model=UserResponse)
async def update_user_role(user_id: str, body: UpdateRoleRequest, request: Request):
    await require_admin(request)
    auth = request.app.state.auth
    success = await auth.update_user_role(user_id, body.role, body.allowed_spaces)
    if not success:
        raise HTTPException(status_code=404, detail="User not found.")
    updated = await auth.get_user_by_id(user_id)
    return updated


# ── SSO / OIDC endpoints ────────────────────────────────────────────────────

@router.get("/sso/login")
async def sso_login(request: Request):
    """Redirect user to the OIDC provider login page."""
    settings = get_settings()
    if not settings.oidc_enabled:
        raise HTTPException(status_code=404, detail="SSO is not enabled.")
    provider = OIDCProvider(settings)
    state = str(uuid.uuid4())
    _sso_state_store.add(state)
    url = await provider.get_authorization_url(state)
    return {"redirect_url": url, "state": state}


# ── TTL-bounded SSO state store (replaces unbounded set) ─────────────────
_SSO_STATE_TTL = 600  # 10 minutes
_SSO_STATE_MAX = 10_000


class _SSOStateStore:
    """In-memory SSO state store with TTL eviction and size cap."""

    def __init__(self) -> None:
        self._states: dict[str, float] = {}  # state → creation time

    def _evict_expired(self) -> None:
        cutoff = time.monotonic() - _SSO_STATE_TTL
        expired = [k for k, v in self._states.items() if v < cutoff]
        for k in expired:
            del self._states[k]

    def add(self, state: str) -> None:
        self._evict_expired()
        if len(self._states) >= _SSO_STATE_MAX:
            # Drop oldest entries to make room
            oldest = sorted(self._states, key=self._states.get)[:100]
            for k in oldest:
                del self._states[k]
        self._states[state] = time.monotonic()

    def validate_and_remove(self, state: str) -> bool:
        self._evict_expired()
        if state in self._states:
            del self._states[state]
            return True
        return False


_sso_state_store = _SSOStateStore()


@router.post("/sso/callback")
async def sso_callback(request: Request):
    """Exchange OIDC authorization code for an Assistant Bot JWT token."""
    settings = get_settings()
    if not settings.oidc_enabled:
        raise HTTPException(status_code=404, detail="SSO is not enabled.")

    body = await request.json()
    code = body.get("code", "")
    state = body.get("state", "")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code.")
    # Validate CSRF state parameter
    if not state or not _sso_state_store.validate_and_remove(state):
        raise HTTPException(status_code=400, detail="Invalid or missing state parameter. Possible CSRF attack.")

    provider = OIDCProvider(settings)
    try:
        oidc_user = await provider.exchange_code(code)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"OIDC authentication failed: {exc}")

    # Map OIDC groups → allowed Confluence spaces
    group_mapping = _json.loads(settings.oidc_group_space_mapping)
    allowed_spaces: list[str] = []
    for group in oidc_user.groups:
        spaces = group_mapping.get(group, [])
        allowed_spaces.extend(s for s in spaces if s not in allowed_spaces)

    # Auto-provision local user or update existing
    auth = request.app.state.auth
    existing = await auth.get_user_by_email(oidc_user.email)
    if existing:
        user_id = existing["id"]
        # Sync spaces from OIDC groups on every login
        if allowed_spaces:
            await auth.update_user_role(user_id, existing.get("role", "user"), allowed_spaces)
    else:
        user_id = str(uuid.uuid4())
        await auth.create_sso_user(user_id, oidc_user.name, oidc_user.email, allowed_spaces)

    token = auth.create_token(user_id, oidc_user.email, oidc_user.name, "user", allowed_spaces)
    return {"token": token, "user": {"id": user_id, "name": oidc_user.name, "email": oidc_user.email, "allowed_spaces": allowed_spaces}}
