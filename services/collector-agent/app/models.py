from typing import Any
from pydantic import BaseModel, Field

class AgentState(BaseModel):
    cluster_id: str | None = None
    agent_token: str | None = None

class LogEnvelope(BaseModel):
    logs: list[dict[str, Any]] = Field(default_factory=list)
