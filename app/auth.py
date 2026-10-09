import hashlib
import os
import secrets
from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import RefreshToken, User, utcnow

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-real-life")
ACCESS_TOKEN_MINUTES = 15
REFRESH_TOKEN_DAYS = 7

bearer = HTTPBearer()


# ---------- passwords ----------
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    salt, digest = stored.split("$")
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return secrets.compare_digest(check, digest)


# ---------- tokens ----------
def create_access_token(user: User, minutes: int = ACCESS_TOKEN_MINUTES) -> str:
    payload = {"sub": str(user.id), "role": user.role, "exp": utcnow() + timedelta(minutes=minutes)}
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_refresh_token(db: Session, user: User) -> str:
    """Random string given to the client. We only store its hash in the DB."""
    token = secrets.token_urlsafe(32)
    db.add(RefreshToken(user_id=user.id, token_hash=_hash_token(token),
                        expires_at=utcnow() + timedelta(days=REFRESH_TOKEN_DAYS)))
    db.commit()
    return token


def use_refresh_token(db: Session, token: str) -> User:
    """Validate a refresh token, delete it (single use / rotation), return its user."""
    row = db.query(RefreshToken).filter_by(token_hash=_hash_token(token)).first()
    if row is None or row.expires_at < utcnow():
        raise HTTPException(401, "Invalid or expired refresh token")
    user = db.get(User, row.user_id)
    db.delete(row)
    db.commit()
    return user


# ---------- dependencies ----------
def get_current_user(creds: HTTPAuthorizationCredentials = Depends(bearer),
                     db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Access token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(401, "User not found")
    return user


def require_role(role: str):
    """Use as a dependency: Depends(require_role("admin"))"""
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role != role:
            raise HTTPException(403, f"{role} access required")
        return user
    return checker
