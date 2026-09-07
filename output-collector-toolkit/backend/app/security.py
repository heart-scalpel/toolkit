import hashlib
import secrets
import time
import uuid
from collections import OrderedDict
from threading import Lock

from fastapi import HTTPException
from pwdlib import PasswordHash
from sqlalchemy import delete, select

from app.models import LoginSession, User, Workspace
from app.validation import empty_workspace

COOKIE_NAME = "output_collector_session"
password_hasher = PasswordHash.recommended()
DUMMY_HASH = password_hasher.hash(secrets.token_urlsafe(32))


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def check_password(password, hashed):
    return password_hasher.verify(password, hashed)


def validate_password(password):
    if not 12 <= len(password) <= 128:
        raise ValueError("密码长度需为 12–128 个字符")
    return password


def new_user(db, username, display_name, password, *, is_admin=False, email=None):
    validate_password(password)
    user = User(
        id=str(uuid.uuid4()),
        username=username,
        email=email,
        display_name=display_name,
        password_hash=password_hasher.hash(password),
        is_admin=is_admin,
        active=True,
        created_at=int(time.time()),
    )
    db.add(user)
    db.flush()
    db.add(Workspace(user_id=user.id, revision=0, state=empty_workspace(), updated_at=int(time.time())))
    db.flush()
    return user


def public_user(user):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
        "is_admin": user.is_admin,
        "active": user.active,
    }


def issue_session(db, user, response, settings, old_token=None):
    now = int(time.time())
    db.execute(delete(LoginSession).where(LoginSession.expires_at <= now))
    if old_token:
        db.execute(delete(LoginSession).where(LoginSession.token_hash == token_hash(old_token)))
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.add(
        LoginSession(
            token_hash=token_hash(token),
            user_id=user.id,
            csrf_token=csrf,
            expires_at=now + settings.session_hours * 3600,
        )
    )
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return {"user": public_user(user), "csrf_token": csrf}


def bootstrap_admin(db, settings):
    if db.scalar(select(User.id).limit(1)):
        return
    if not settings.bootstrap_admin_password:
        return
    # Reuse the API's username rules without importing the application.
    from app.contracts import AccountName

    username = AccountName(username=settings.bootstrap_admin_username).username
    new_user(db, username, "管理员", settings.bootstrap_admin_password.get_secret_value(), is_admin=True)
    db.commit()


class LoginLimiter:
    """Bounded, per-process admission limiter. Deployment must keep one worker."""

    def __init__(self):
        self.buckets = OrderedDict()
        self.lock = Lock()

    def admit(self, ip, username):
        now = time.monotonic()
        keys = [("ip:" + ip, 30), ("user:" + token_hash(username), 10)]
        with self.lock:
            for key, limit in keys:
                attempts = [t for t in self.buckets.get(key, []) if now - t < 60]
                self.buckets[key] = attempts
                self.buckets.move_to_end(key)
                if len(attempts) >= limit:
                    raise HTTPException(429, "操作过于频繁，请一分钟后重试", headers={"Retry-After": "60"})
            for key, _ in keys:
                self.buckets[key].append(now)
            while len(self.buckets) > 10000:
                self.buckets.popitem(last=False)
