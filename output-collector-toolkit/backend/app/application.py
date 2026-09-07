import secrets
import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import delete, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, Settings
from app.contracts import (
    CreateUserInput,
    LoginInput,
    PasswordInput,
    RegisterInput,
    UserUpdate,
    WorkspaceInput,
)
from app.database import create_database_engine, migrate
from app.models import LoginSession, User, Workspace
from app.security import (
    COOKIE_NAME,
    DUMMY_HASH,
    LoginLimiter,
    bootstrap_admin,
    check_password,
    issue_session,
    new_user,
    password_hasher,
    public_user,
    token_hash,
)
from app.validation import validate_workspace


def create_app(settings: Settings | None = None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        engine = create_database_engine(settings)
        try:
            migrate(engine)
            with Session(engine) as db:
                bootstrap_admin(db, settings)
            app.state.engine = engine
            app.state.login_limiter = LoginLimiter()
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="Output 收集器", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(_request, _exc):
        # Do not echo passwords or complete pasted material in validation errors.
        return JSONResponse({"detail": "输入格式不正确，请检查账号、密码长度和必填项"}, status_code=422)

    @app.middleware("http")
    async def request_boundary(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin is not None and origin != settings.public_origin:
                return JSONResponse({"detail": "请求来源不匹配，请从配置的访问地址打开"}, status_code=403)
            if request.headers.get("x-collector-request") != "1":
                return JSONResponse({"detail": "缺少请求校验头"}, status_code=403)
            if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
                return JSONResponse({"detail": "请使用 JSON 请求"}, status_code=415)
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > settings.max_body_bytes:
                    return JSONResponse({"detail": "内容超过服务器大小限制，请减少批次"}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            "img-src data:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        )
        return response

    def get_db(request: Request):
        with Session(request.app.state.engine, expire_on_commit=False) as db:
            yield db

    DB = Annotated[Session, Depends(get_db)]

    def current_session(request: Request, db: DB):
        token = request.cookies.get(COOKIE_NAME, "")
        login = db.get(LoginSession, token_hash(token)) if token else None
        user = db.get(User, login.user_id) if login else None
        if not login or login.expires_at <= time.time() or not user or not user.active:
            raise HTTPException(401, "登录已失效，请重新登录")
        if request.method not in {"GET", "HEAD"}:
            presented_csrf = request.headers.get("x-csrf-token", "")
            if not presented_csrf.isascii() or not secrets.compare_digest(presented_csrf, login.csrf_token):
                raise HTTPException(403, "登录状态已变化，请重新登录后继续")
        return user, login

    Principal = Annotated[tuple, Depends(current_session)]

    def administrator(principal: Principal):
        user, _ = principal
        if not user.is_admin:
            raise HTTPException(403, "此操作需要管理员账号")
        return user

    Admin = Annotated[User, Depends(administrator)]

    @app.get("/health")
    def health(db: DB):
        db.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.get("/")
    @app.get("/index.html")
    def index():
        return FileResponse(PROJECT_ROOT / "index.html", media_type="text/html")

    @app.post("/api/auth/login")
    def login(body: LoginInput, request: Request, response: Response, db: DB):
        request.app.state.login_limiter.admit(
            request.client.host if request.client else "unknown", body.username
        )
        user = db.scalar(select(User).where(or_(User.email == body.username, User.username == body.username)))
        hashed = user.password_hash if user else DUMMY_HASH
        valid = check_password(body.password.get_secret_value(), hashed)
        if not valid or not user or not user.active:
            raise HTTPException(401, "账号或密码不正确")
        return issue_session(db, user, response, settings, request.cookies.get(COOKIE_NAME))

    @app.post("/api/auth/register", status_code=201)
    def register(body: RegisterInput, request: Request, response: Response, db: DB):
        request.app.state.login_limiter.admit(
            request.client.host if request.client else "unknown", body.email
        )
        try:
            user = new_user(
                db,
                "user-" + uuid.uuid4().hex,
                body.email.split("@", 1)[0][:80],
                body.password.get_secret_value(),
                email=body.email,
            )
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "这个邮箱已经注册，请直接登录") from None
        # Account, empty workspace, and login session commit together.
        return issue_session(db, user, response, settings, request.cookies.get(COOKIE_NAME))

    @app.get("/api/auth/me")
    def me(principal: Principal):
        user, login = principal
        return {"user": public_user(user), "csrf_token": login.csrf_token}

    @app.post("/api/auth/logout")
    def logout(principal: Principal, db: DB, response: Response):
        _, login = principal
        db.delete(login)
        db.commit()
        response.delete_cookie(
            COOKIE_NAME, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax"
        )
        return {"ok": True}

    @app.post("/api/auth/password")
    def password(body: PasswordInput, principal: Principal, db: DB, response: Response):
        user, _ = principal
        if not check_password(body.current_password.get_secret_value(), user.password_hash):
            raise HTTPException(400, "当前密码不正确")
        user.password_hash = password_hasher.hash(body.new_password.get_secret_value())
        db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
        return issue_session(db, user, response, settings)

    @app.get("/api/workspace")
    def read_workspace(principal: Principal, db: DB):
        user, _ = principal
        workspace = db.get(Workspace, user.id)
        return {
            "account_id": user.id,
            "revision": workspace.revision,
            "state": workspace.state,
            "updated_at": workspace.updated_at,
        }

    @app.put("/api/workspace")
    def save_workspace(body: WorkspaceInput, principal: Principal, db: DB):
        user, _ = principal
        if body.account_id != user.id:
            raise HTTPException(409, "当前账号已变化，请重新登录")
        try:
            state = validate_workspace(body.state)
        except (ValueError, RecursionError) as exc:
            raise HTTPException(422, str(exc)) from None
        now = int(time.time())
        result = db.execute(
            update(Workspace)
            .where(Workspace.user_id == user.id, Workspace.revision == body.revision)
            .values(state=state, revision=body.revision + 1, updated_at=now)
        )
        if result.rowcount != 1:
            raise HTTPException(409, "其他窗口已更新数据。本次未覆盖，请加载服务器最新内容后重试")
        db.commit()
        return {"account_id": user.id, "revision": body.revision + 1, "updated_at": now}

    @app.get("/api/admin/users")
    def users(_admin: Admin, db: DB):
        return [
            public_user(user) for user in db.scalars(select(User).order_by(User.created_at, User.username))
        ]

    @app.post("/api/admin/users", status_code=201)
    def create_user(body: CreateUserInput, _admin: Admin, db: DB):
        try:
            user = new_user(db, body.username, body.display_name, body.password.get_secret_value())
            db.commit()
        except IntegrityError:
            raise HTTPException(409, "这个账号已存在") from None
        return public_user(user)

    @app.patch("/api/admin/users/{user_id}")
    def update_user(user_id: str, body: UserUpdate, _admin: Admin, db: DB):
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(404, "账号不存在")
        if user.is_admin:
            raise HTTPException(400, "管理员请使用修改密码；恢复账号可使用服务器管理命令")
        if body.active is not None:
            user.active = body.active
        if body.password is not None:
            user.password_hash = password_hasher.hash(body.password.get_secret_value())
        if body.active is False or body.password is not None:
            db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
        db.commit()
        return public_user(user)

    return app
