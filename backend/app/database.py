from __future__ import annotations

import logging
from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DATA_DIR, get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None
_db_fallback_warning: str | None = None
_active_db_kind: str = "sqlite"


def get_db_fallback_warning() -> str | None:
    return _db_fallback_warning


def get_active_db_kind() -> str:
    return _active_db_kind


def build_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_settings().resolved_database_url()
    connect_args: dict[str, Any] = {}
    engine_kwargs: dict[str, Any] = {"future": True}

    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    else:
        engine_kwargs["pool_pre_ping"] = True
        engine_kwargs["pool_recycle"] = 300

    return create_engine(url, connect_args=connect_args, **engine_kwargs)


def init_db(database_url: str | None = None) -> None:
    global _engine, _SessionLocal, _db_fallback_warning, _active_db_kind
    from . import models  # noqa: F401

    target_url = database_url or get_settings().resolved_database_url()
    _db_fallback_warning = None

    try:
        eng = build_engine(target_url)
        Base.metadata.create_all(bind=eng)
        _engine = eng
        _active_db_kind = "postgresql" if target_url.startswith("postgresql") else "sqlite"
    except Exception as exc:
        if database_url is not None or target_url.startswith("sqlite"):
            raise
        logger.error(
            "Primary PostgreSQL database unavailable (%s); falling back to local SQLite so service stays online.",
            exc,
        )
        _db_fallback_warning = (
            f"云端 PostgreSQL 暂时不可用（已自动降级为临时本地数据库，服务可正常使用，请检查 Neon 配额或更换 DATABASE_URL）：{str(exc)[:180]}"
        )
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        fallback_url = f"sqlite:///{DATA_DIR / 'radar.db'}"
        eng = build_engine(fallback_url)
        Base.metadata.create_all(bind=eng)
        _engine = eng
        _active_db_kind = "sqlite"

    _SessionLocal = sessionmaker(
        bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False
    )


def get_session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        init_db()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
