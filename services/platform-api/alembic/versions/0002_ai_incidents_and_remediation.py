"""add ai incidents and remediation schema

Revision ID: 0002_ai_incidents_and_remediation
Revises: 0001_initial
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_ai_incidents_and_remediation"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "ai_log_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cluster_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_kind", sa.Text(), nullable=True),
        sa.Column("resource_name", sa.Text(), nullable=True),
        sa.Column("namespace", sa.Text(), nullable=True),
        sa.Column("pod_name", sa.Text(), nullable=True),
        sa.Column("container_name", sa.Text(), nullable=True),
        sa.Column("workload_kind", sa.Text(), nullable=True),
        sa.Column("workload_name", sa.Text(), nullable=True),
        sa.Column("log_signature", sa.Text(), nullable=False),
        sa.Column("matched_pattern", sa.Text(), nullable=True),
        sa.Column("raw_evidence_sample", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("preliminary_severity", sa.Text(), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_ai_log_findings_organization_id", "ai_log_findings", ["organization_id"])
    op.create_index("ix_ai_log_findings_cluster_id", "ai_log_findings", ["cluster_id"])

    op.create_table(
        "ai_incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cluster_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_kind", sa.Text(), nullable=True),
        sa.Column("resource_name", sa.Text(), nullable=True),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("incident_type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("namespace", sa.Text(), nullable=True),
        sa.Column("pod_name", sa.Text(), nullable=True),
        sa.Column("container_name", sa.Text(), nullable=True),
        sa.Column("workload_kind", sa.Text(), nullable=True),
        sa.Column("workload_name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
    )
    op.create_index("ix_ai_incidents_organization_id", "ai_incidents", ["organization_id"])
    op.create_index("ix_ai_incidents_cluster_id", "ai_incidents", ["cluster_id"])

    op.create_table(
        "remediation_suggestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cluster_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_incidents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_kind", sa.Text(), nullable=True),
        sa.Column("resource_name", sa.Text(), nullable=True),
        sa.Column("suggestion_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.Text(), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_executable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("executable_action_type", sa.Text(), nullable=True),
        sa.Column("action_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ai_model", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        *timestamps(),
    )
    op.create_index("ix_remediation_suggestions_organization_id", "remediation_suggestions", ["organization_id"])
    op.create_index("ix_remediation_suggestions_cluster_id", "remediation_suggestions", ["cluster_id"])
    op.create_index("ix_remediation_suggestions_incident_id", "remediation_suggestions", ["incident_id"])

    op.create_table(
        "remediation_approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cluster_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("suggestion_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("remediation_suggestions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approval_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("approval_reason", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_remediation_approvals_organization_id", "remediation_approvals", ["organization_id"])
    op.create_index("ix_remediation_approvals_cluster_id", "remediation_approvals", ["cluster_id"])
    op.create_index("ix_remediation_approvals_suggestion_id", "remediation_approvals", ["suggestion_id"])

    op.create_table(
        "remediation_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cluster_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("suggestion_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("remediation_suggestions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("remediation_approvals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("action_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("picked_up_by_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("picked_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_remediation_actions_organization_id", "remediation_actions", ["organization_id"])
    op.create_index("ix_remediation_actions_cluster_id", "remediation_actions", ["cluster_id"])
    op.create_index("ix_remediation_actions_suggestion_id", "remediation_actions", ["suggestion_id"])
    op.create_index("ix_remediation_actions_approval_id", "remediation_actions", ["approval_id"])

    op.create_table(
        "ai_cluster_queries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cluster_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("parsed_query", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("answer_summary", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ai_model", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ai_cluster_queries_organization_id", "ai_cluster_queries", ["organization_id"])
    op.create_index("ix_ai_cluster_queries_cluster_id", "ai_cluster_queries", ["cluster_id"])

    op.add_column("audit_logs", sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("audit_logs", sa.Column("ip_address", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_logs", "ip_address")
    op.drop_column("audit_logs", "agent_id")

    for index_name in [
        "ix_ai_cluster_queries_cluster_id",
        "ix_ai_cluster_queries_organization_id",
    ]:
        op.drop_index(index_name, table_name="ai_cluster_queries")
    op.drop_table("ai_cluster_queries")

    for index_name in [
        "ix_remediation_actions_approval_id",
        "ix_remediation_actions_suggestion_id",
        "ix_remediation_actions_cluster_id",
        "ix_remediation_actions_organization_id",
    ]:
        op.drop_index(index_name, table_name="remediation_actions")
    op.drop_table("remediation_actions")

    for index_name in [
        "ix_remediation_approvals_suggestion_id",
        "ix_remediation_approvals_cluster_id",
        "ix_remediation_approvals_organization_id",
    ]:
        op.drop_index(index_name, table_name="remediation_approvals")
    op.drop_table("remediation_approvals")

    for index_name in [
        "ix_remediation_suggestions_incident_id",
        "ix_remediation_suggestions_cluster_id",
        "ix_remediation_suggestions_organization_id",
    ]:
        op.drop_index(index_name, table_name="remediation_suggestions")
    op.drop_table("remediation_suggestions")

    for index_name in [
        "ix_ai_incidents_cluster_id",
        "ix_ai_incidents_organization_id",
    ]:
        op.drop_index(index_name, table_name="ai_incidents")
    op.drop_table("ai_incidents")

    for index_name in [
        "ix_ai_log_findings_cluster_id",
        "ix_ai_log_findings_organization_id",
    ]:
        op.drop_index(index_name, table_name="ai_log_findings")
    op.drop_table("ai_log_findings")
