import uuid
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    users = relationship("User", back_populates="organization")

class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, default="owner")
    organization = relationship("Organization", back_populates="users")

class AgentKey(Base):
    __tablename__ = "agent_keys"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    key_last4: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Cluster(Base, TimestampMixin):
    __tablename__ = "clusters"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_clusters_org_name"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, default="aks")
    kube_system_uid: Mapped[str | None] = mapped_column(Text)
    agent_version: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class LogBatch(Base):
    __tablename__ = "log_batches"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    cluster_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    blob_path: Mapped[str] = mapped_column(Text, nullable=False)
    log_count: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ClusterSnapshot(Base):
    __tablename__ = "cluster_snapshots"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    cluster_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    snapshot_type: Mapped[str] = mapped_column(Text, nullable=False)
    blob_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Issue(Base):
    __tablename__ = "issues"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    cluster_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    namespace: Mapped[str | None] = mapped_column(Text)
    workload: Mapped[str | None] = mapped_column(Text)
    pod_name: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    issue_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="open")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class AIRecommendation(Base):
    __tablename__ = "ai_recommendations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    cluster_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    issue_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("issues.id", ondelete="SET NULL"))
    recommendation_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class AILogFinding(Base, TimestampMixin):
    __tablename__ = "ai_log_findings"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    cluster_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    resource_kind: Mapped[str | None] = mapped_column(Text)
    resource_name: Mapped[str | None] = mapped_column(Text)
    namespace: Mapped[str | None] = mapped_column(Text)
    pod_name: Mapped[str | None] = mapped_column(Text)
    container_name: Mapped[str | None] = mapped_column(Text)
    workload_kind: Mapped[str | None] = mapped_column(Text)
    workload_name: Mapped[str | None] = mapped_column(Text)
    log_signature: Mapped[str] = mapped_column(Text, nullable=False)
    matched_pattern: Mapped[str | None] = mapped_column(Text)
    raw_evidence_sample: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    preliminary_severity: Mapped[str] = mapped_column(Text, nullable=False)

class AIIncident(Base, TimestampMixin):
    __tablename__ = "ai_incidents"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    cluster_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    resource_kind: Mapped[str | None] = mapped_column(Text)
    resource_name: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    incident_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="open")
    namespace: Mapped[str | None] = mapped_column(Text)
    pod_name: Mapped[str | None] = mapped_column(Text)
    container_name: Mapped[str | None] = mapped_column(Text)
    workload_kind: Mapped[str | None] = mapped_column(Text)
    workload_name: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class RemediationSuggestion(Base, TimestampMixin):
    __tablename__ = "remediation_suggestions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    cluster_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    incident_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_incidents.id", ondelete="CASCADE"), index=True)
    resource_kind: Mapped[str | None] = mapped_column(Text)
    resource_name: Mapped[str | None] = mapped_column(Text)
    suggestion_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(Text, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(default=True)
    is_executable: Mapped[bool] = mapped_column(default=False)
    executable_action_type: Mapped[str | None] = mapped_column(Text)
    action_payload: Mapped[dict | None] = mapped_column(JSONB)
    ai_model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    confidence_score: Mapped[float | None] = mapped_column(Float)

class RemediationApproval(Base):
    __tablename__ = "remediation_approvals"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    cluster_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    suggestion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("remediation_suggestions.id", ondelete="CASCADE"), index=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    approval_status: Mapped[str] = mapped_column(Text, default="pending")
    approval_reason: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class RemediationAction(Base):
    __tablename__ = "remediation_actions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    cluster_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    suggestion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("remediation_suggestions.id", ondelete="CASCADE"), index=True)
    approval_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("remediation_approvals.id", ondelete="CASCADE"), index=True)
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    action_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, default="queued")
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    picked_up_by_agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONB)

class AIClusterQuery(Base):
    __tablename__ = "ai_cluster_queries"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    cluster_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    question: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_query: Mapped[dict | None] = mapped_column(JSONB)
    answer_summary: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONB)
    ai_model: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class AlertLimit(Base, TimestampMixin):
    __tablename__ = "alert_limits"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    cluster_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    metric_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False, default="cluster")
    namespace: Mapped[str | None] = mapped_column(Text)
    workload_name: Mapped[str | None] = mapped_column(Text)
    resource_id: Mapped[str | None] = mapped_column(Text)
    operator: Mapped[str] = mapped_column(Text, nullable=False)
    threshold_value: Mapped[float] = mapped_column(Float, nullable=False)
    time_window_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    severity: Mapped[str] = mapped_column(Text, nullable=False, default="major")
    email_enabled: Mapped[bool] = mapped_column(default=True)
    notification_email: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=True)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class AlertEvent(Base):
    __tablename__ = "alert_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    cluster_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    alert_limit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("alert_limits.id", ondelete="CASCADE"), index=True)
    metric_value: Mapped[float | None] = mapped_column(Float)
    threshold_value: Mapped[float] = mapped_column(Float, nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notification_sent: Mapped[bool] = mapped_column(default=False)
    notification_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ClusterMetricSample(Base):
    __tablename__ = "cluster_metric_samples"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    cluster_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    namespace: Mapped[str | None] = mapped_column(Text)
    resource_kind: Mapped[str] = mapped_column(Text, nullable=False)
    resource_name: Mapped[str] = mapped_column(Text, nullable=False)
    container_name: Mapped[str | None] = mapped_column(Text)
    node_name: Mapped[str | None] = mapped_column(Text)
    metric_name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("clusters.id", ondelete="SET NULL"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
