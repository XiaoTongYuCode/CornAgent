from collections.abc import Iterator
from dataclasses import dataclass
from ipaddress import IPv6Address, ip_address
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.persistence.scope import LOCAL_SCOPE, Identity


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.database.session_factory() as db:
        yield db


def get_scope(request: Request) -> Identity:
    return request.app.state.identity_provider.authenticate(request)


def get_run_rate_limit_identity(request: Request) -> Identity:
    """Use the ASGI client address only for admission, never for storage ownership.

    Trusted proxy processing belongs to the ASGI server. Reading forwarded headers
    here would let direct clients choose their own rate-limit bucket.
    """
    if request.app.state.settings.users_enabled:
        return get_scope(request)
    try:
        address = ip_address(request.client.host if request.client else "")
        if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        user_id = str(address)
    except ValueError:
        # Missing/invalid transport addresses share a bounded bucket.
        user_id = "unknown"
    return Identity(user_id=f"ip:{user_id}", tenant_id=LOCAL_SCOPE.tenant_id)


@dataclass(frozen=True, slots=True)
class StreamAuthentication:
    identity: Identity = LOCAL_SCOPE


def get_stream_scope(request: Request) -> StreamAuthentication:
    return StreamAuthentication(identity=get_scope(request))


Db = Annotated[Session, Depends(get_db)]
CurrentIdentity = Annotated[Identity, Depends(get_scope)]
StreamIdentity = Annotated[StreamAuthentication, Depends(get_stream_scope)]
