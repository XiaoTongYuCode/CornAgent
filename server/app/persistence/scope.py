"""Shared storage scope for the standalone workspace.

The runtime, checkpoints and tools use the same fixed identity for every browser.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Identity:
    user_id: str = "local"
    tenant_id: str = "cornagent"
    membership_id: str = "local"


LOCAL_SCOPE = Identity()
