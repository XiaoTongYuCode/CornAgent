from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.persistence.scope import LOCAL_SCOPE, Identity


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.database.session_factory() as db:
        yield db


def get_scope() -> Identity:
    return LOCAL_SCOPE


@dataclass(frozen=True, slots=True)
class StreamAuthentication:
    identity: Identity = LOCAL_SCOPE


def get_stream_scope() -> StreamAuthentication:
    return StreamAuthentication()


Db = Annotated[Session, Depends(get_db)]
CurrentIdentity = Annotated[Identity, Depends(get_scope)]
StreamIdentity = Annotated[StreamAuthentication, Depends(get_stream_scope)]
