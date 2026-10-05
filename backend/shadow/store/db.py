from pathlib import Path
from typing import Iterator
from fastapi import Request
from sqlalchemy import Engine
from sqlmodel import SQLModel, Session, create_engine
from shadow.store import models  # noqa: F401  (registers tables)


def make_engine(data_dir: Path) -> Engine:
    data_dir.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{data_dir / 'shadow.db'}", connect_args={"check_same_thread": False})


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as s:
        yield s
