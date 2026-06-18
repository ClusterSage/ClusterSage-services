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

class AgentCapabilitiesRequest(BaseModel):
    remediation_enabled: bool = False
    cluster_wide: bool = False
    allowed_namespaces: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    agent_version: str | None = None

class AgentActionStatusRequest(BaseModel):
    status: str = Field(pattern="^(running|succeeded|failed|cancelled)$")
    error_message: str | None = Field(default=None, max_length=4000)
    result: dict[str, Any] | None = None

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

class AILogFindingResponse(BaseModel):
    id: UUID
    cluster_id: UUID
    resource_kind: str | None = None
    resource_name: str | None = None
    namespace: str | None = None
    pod_name: str | None = None
    container_name: str | None = None
    workload_kind: str | None = None
    workload_name: str | None = None
    log_signature: str
    matched_pattern: str | None = None
    raw_evidence_sample: dict[str, Any]
    first_seen_at: datetime
    last_seen_at: datetime
    occurrence_count: int
    preliminary_severity: str
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

class AIIncidentResponse(BaseModel):
    id: UUID
    cluster_id: UUID
    resource_kind: str | None = None
    resource_name: str | None = None
    scope: str
    title: str
    incident_type: str
    severity: str
    status: str
    namespace: str | None = None
    pod_name: str | None = None
    container_name: str | None = None
    workload_kind: str | None = None
    workload_name: str | None = None
    description: str | None = None
    ai_summary: str | None = None
    evidence: dict[str, Any]
    confidence_score: float | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    occurrence_count: int
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    model_config = {"from_attributes": True}

class RemediationSuggestionResponse(BaseModel):
    id: UUID
    cluster_id: UUID
    incident_id: UUID
    resource_kind: str | None = None
    resource_name: str | None = None
    suggestion_type: str
    title: str
    summary: str
    risk_level: str
    requires_approval: bool
    is_executable: bool
    executable_action_type: str | None = None
    action_payload: dict[str, Any] | None = None
    ai_model: str | None = None
    prompt_version: str | None = None
    confidence_score: float | None = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

class RemediationDecisionRequest(BaseModel):
    approval_reason: str | None = Field(default=None, max_length=1000)
    confirmation_text: str | None = Field(default=None, max_length=100)

class RemediationApprovalResultResponse(BaseModel):
    suggestion_id: UUID
    approval_id: UUID
    approval_status: str
    action_id: UUID | None = None
    action_status: str | None = None
    message: str

class ResourceAISuggestionResponse(BaseModel):
    id: UUID
    cluster_id: UUID
    incident_id: UUID
    incident_title: str
    incident_severity: str
    incident_status: str
    resource_kind: str | None = None
    resource_name: str | None = None
    suggestion_type: str
    title: str
    summary: str
    risk_level: str
    requires_approval: bool
    is_executable: bool
    executable_action_type: str | None = None
    action_payload: dict[str, Any] | None = None
    ai_model: str | None = None
    prompt_version: str | None = None
    confidence_score: float | None = None
    latest_approval_status: str | None = None
    latest_action_id: UUID | None = None
    latest_action_status: str | None = None
    approval_available: bool = False
    approval_block_reason: str | None = None
    created_at: datetime
    updated_at: datetime

class RemediationApprovalResponse(BaseModel):
    id: UUID
    cluster_id: UUID
    suggestion_id: UUID
    approved_by_user_id: UUID | None = None
    approval_status: str
    approval_reason: str | None = None
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    created_at: datetime
    model_config = {"from_attributes": True}

class RemediationActionResponse(BaseModel):
    id: UUID
    cluster_id: UUID
    suggestion_id: UUID
    approval_id: UUID
    action_type: str
    action_payload: dict[str, Any]
    status: str
    requested_by_user_id: UUID | None = None
    picked_up_by_agent_id: UUID | None = None
    requested_at: datetime
    picked_up_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    result: dict[str, Any] | None = None
    model_config = {"from_attributes": True}

class AgentActionPollResponse(BaseModel):
    actions: list[RemediationActionResponse] = Field(default_factory=list)

class AIClusterQueryResponse(BaseModel):
    id: UUID
    cluster_id: UUID
    user_id: UUID | None = None
    question: str
    parsed_query: dict[str, Any] | None = None
    answer_summary: str | None = None
    result: dict[str, Any] | None = None
    ai_model: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


class AIClusterQueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)

class AuditLogResponse(BaseModel):
    id: UUID
    action: str
    actor_type: str
    details: dict[str, Any] | None
    agent_id: UUID | None = None
    ip_address: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}

class AlertLimitCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    metric_type: str = Field(min_length=1, max_length=100)
    scope_type: str = Field(pattern="^(cluster|namespace|workload|resource)$")
    namespace: str | None = Field(default=None, max_length=120)
    workload_name: str | None = Field(default=None, max_length=200)
    resource_id: str | None = Field(default=None, max_length=300)
    operator: str = Field(pattern="^(gt|gte|lt|lte|eq)$")
    threshold_value: float
    time_window_minutes: int = Field(ge=1, le=1440)
    severity: str = Field(pattern="^(minor|major|critical)$")
    email_enabled: bool = True
    notification_email: EmailStr | None = None
    enabled: bool = True
    cooldown_minutes: int = Field(ge=1, le=10080, default=30)

class AlertLimitUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    metric_type: str | None = Field(default=None, min_length=1, max_length=100)
    scope_type: str | None = Field(default=None, pattern="^(cluster|namespace|workload|resource)$")
    namespace: str | None = Field(default=None, max_length=120)
    workload_name: str | None = Field(default=None, max_length=200)
    resource_id: str | None = Field(default=None, max_length=300)
    operator: str | None = Field(default=None, pattern="^(gt|gte|lt|lte|eq)$")
    threshold_value: float | None = None
    time_window_minutes: int | None = Field(default=None, ge=1, le=1440)
    severity: str | None = Field(default=None, pattern="^(minor|major|critical)$")
    email_enabled: bool | None = None
    notification_email: EmailStr | None = None
    enabled: bool | None = None
    cooldown_minutes: int | None = Field(default=None, ge=1, le=10080)

class AlertLimitResponse(BaseModel):
    id: UUID
    cluster_id: UUID
    created_by_user_id: UUID | None = None
    name: str
    metric_type: str
    scope_type: str
    namespace: str | None = None
    workload_name: str | None = None
    resource_id: str | None = None
    operator: str
    threshold_value: float
    time_window_minutes: int
    severity: str
    email_enabled: bool
    notification_email: EmailStr | None = None
    enabled: bool
    cooldown_minutes: int
    last_triggered_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

class AlertEventResponse(BaseModel):
    id: UUID
    cluster_id: UUID
    alert_limit_id: UUID
    metric_value: float | None = None
    threshold_value: float
    triggered_at: datetime
    notification_sent: bool
    notification_error: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}
