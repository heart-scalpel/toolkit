"""Operator tools. Passwords are entered interactively, never as CLI arguments."""

import argparse
import getpass
import sqlite3
from pathlib import Path

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import create_database_engine, migrate
from app.models import LoginSession, User
from app.security import password_hasher, validate_password


def backup_database(source: Path, destination: Path):
    if not source.is_file():
        raise ValueError("数据库不存在")
    if destination.exists():
        raise ValueError("备份目标已存在，请换一个文件名")
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as db:
        with sqlite3.connect(destination) as backup:
            db.backup(backup)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    reset = sub.add_parser("reset-password")
    reset.add_argument("username")
    backup = sub.add_parser("backup-db")
    backup.add_argument("destination", type=Path)
    args = parser.parse_args()
    settings = Settings()
    if args.command == "backup-db":
        backup_database(settings.database_path, args.destination)
        print("数据库备份已完成")
        return
    password = validate_password(getpass.getpass("新密码（12–128 字符）: "))
    if password != getpass.getpass("再次输入: "):
        parser.error("两次密码不一致")
    engine = create_database_engine(settings)
    try:
        migrate(engine)
        with Session(engine) as db:
            identity = args.username.strip().lower()
            user = db.scalar(select(User).where(or_(User.email == identity, User.username == identity)))
            if not user:
                parser.error("账号不存在")
            user.password_hash = password_hasher.hash(password)
            user.active = True
            db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
            db.commit()
        print("密码已重置，旧登录已失效")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
