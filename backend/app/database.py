from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


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
    global _engine, _SessionLocal
    _engine = build_engine(database_url)
    _SessionLocal = sessionmaker(
        bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=_engine)


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
