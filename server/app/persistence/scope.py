"""Runtime ownership contract; LOCAL_SCOPE is used only with users disabled."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Identity:
    user_id: str = "local"
    tenant_id: str = "cornagent"
    membership_id: str = "local"


LOCAL_SCOPE = Identity()
