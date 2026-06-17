from typing import Any
from pydantic import BaseModel, Field

class AgentState(BaseModel):
    cluster_id: str | None = None
    agent_token: str | None = None
    capabilities_reported: bool = False
    active_action_ids: set[str] = Field(default_factory=set)
    completed_action_ids: set[str] = Field(default_factory=set)

class LogEnvelope(BaseModel):
    logs: list[dict[str, Any]] = Field(default_factory=list)
