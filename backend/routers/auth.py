"""
routers/auth.py — /auth/* endpoints (register, login, whoami, self-service
change-password), moved verbatim out of api.py during the router split.
No logic changed from what api.py had before.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from assistant import auth, db, rate_limit

from ._shared import get_current_user

router = APIRouter()


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class WhoAmIResponse(BaseModel):
    username: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/auth/register", response_model=TokenResponse)
def register(payload: RegisterRequest) -> TokenResponse:
    username = payload.username.strip()
    if not username or len(username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters.")
    if not payload.password or len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    created = db.create_account(username, auth.hash_password(payload.password))
    if not created:
        raise HTTPException(status_code=409, detail="That username is already taken.")

    return TokenResponse(access_token=auth.create_access_token(username), username=username)


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request) -> TokenResponse:
    username = payload.username.strip()
    client_ip = request.client.host if request.client else "unknown"

    # Locked out by EITHER key -- repeated failures against this one
    # username, or repeated failures from this one source regardless of
    # which username(s) it's trying.
    if rate_limit.is_locked_out("user", username) or rate_limit.is_locked_out("ip", client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Try again in a few minutes.",
        )

    password_hash = db.get_password_hash(username)
    # Same error for "no such user" and "wrong password" -- distinguishing
    # them tells an attacker which usernames exist.
    if not password_hash or not auth.verify_password(payload.password, password_hash):
        rate_limit.record_failure("user", username)
        rate_limit.record_failure("ip", client_ip)
        raise HTTPException(status_code=401, detail="Incorrect username or password.")

    rate_limit.clear_failures("user", username)
    rate_limit.clear_failures("ip", client_ip)
    return TokenResponse(access_token=auth.create_access_token(username), username=username)


@router.get("/auth/me", response_model=WhoAmIResponse)
def whoami(user_id: str = Depends(get_current_user)) -> WhoAmIResponse:
    """Lets the frontend confirm a stored JWT (from a browser cookie) is
    still valid and recover the username it belongs to after a page reload,
    without the user having to log in again just because the page reloaded.
    """
    return WhoAmIResponse(username=user_id)


@router.post("/auth/change-password")
def change_password(
    payload: ChangePasswordRequest, user_id: str = Depends(get_current_user)
) -> dict:
    """Self-service -- proves identity with the CURRENT password, not the
    admin password (that gates the shared document library, not a person's
    own account). Doesn't help if you've actually forgotten your password;
    see /auth/admin-reset-password for that.
    """
    password_hash = db.get_password_hash(user_id)
    if not password_hash or not auth.verify_password(payload.current_password, password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    db.set_password_hash(user_id, auth.hash_password(payload.new_password))
    return {"changed": True}
