from datetime import datetime
from typing import Any
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str | None = None
    organization_name: str = Field(min_length=2)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserResponse(BaseModel):
    id: UUID
    organization_id: UUID
    email: EmailStr
    full_name: str | None
    role: str
    model_config = {"from_attributes": True}

class AgentKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_at: datetime | None = None

class AgentKeyResponse(BaseModel):
    id: UUID
    name: str
    key_last4: str
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    raw_key: str | None = None
    model_config = {"from_attributes": True}

class AgentRegisterRequest(BaseModel):
    email: EmailStr
    access_key: str
    cluster_name: str = Field(min_length=1, max_length=150)
    provider: str = "aks"
    kube_system_uid: str | None = None
    agent_version: str | None = None

class AgentRegisterResponse(BaseModel):
    cluster_id: UUID
    agent_token: str

class HeartbeatRequest(BaseModel):
    status: str = "healthy"
    agent_version: str | None = None

class LogsIngestRequest(BaseModel):
    logs: list[dict[str, Any]] = Field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None

class EventsIngestRequest(BaseModel):
    events: list[dict[str, Any]] = Field(default_factory=list)

class SnapshotIngestRequest(BaseModel):
    snapshot_type: str = "full"
    snapshot: dict[str, Any]

class ClusterResponse(BaseModel):
    id: UUID
    name: str
    provider: str
    status: str
    agent_version: str | None
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

class LogBatchResponse(BaseModel):
    id: UUID
    blob_path: str
    log_count: int
    size_bytes: int
    start_time: datetime | None
    end_time: datetime | None
    created_at: datetime
    model_config = {"from_attributes": True}

class SnapshotResponse(BaseModel):
    id: UUID
    snapshot_type: str
    blob_path: str
    created_at: datetime
    model_config = {"from_attributes": True}

class ResourceSummary(BaseModel):
    name: str
    namespace: str | None = None
    kind: str
    status: str | None = None
    age: str | None = None
    node_name: str | None = None
    restart_count: int | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    last_updated_at: datetime | None = None
    created_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class ResourceLogEntry(BaseModel):
    timestamp: str | None = None
    namespace: str | None = None
    pod: str | None = None
    container: str | None = None
    message: str
    raw: dict[str, Any] = Field(default_factory=dict)

class IssueResponse(BaseModel):
    id: UUID
    namespace: str | None
    workload: str | None
    pod_name: str | None
    severity: str
    issue_type: str
    title: str
    description: str | None
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    model_config = {"from_attributes": True}

class AuditLogResponse(BaseModel):
    id: UUID
    action: str
    actor_type: str
    details: dict[str, Any] | None
    created_at: datetime
    model_config = {"from_attributes": True}
