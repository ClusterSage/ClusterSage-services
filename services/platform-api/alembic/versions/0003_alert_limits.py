"""add alert limits and alert events

Revision ID: 0003_alert_limits
Revises: 0002_ai_incidents_remediation
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_alert_limits"
down_revision = "0002_ai_incidents_remediation"
branch_labels = None
depends_on = None


def timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "alert_limits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cluster_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("metric_type", sa.Text(), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False, server_default="cluster"),
        sa.Column("namespace", sa.Text(), nullable=True),
        sa.Column("workload_name", sa.Text(), nullable=True),
        sa.Column("resource_id", sa.Text(), nullable=True),
        sa.Column("operator", sa.Text(), nullable=False),
        sa.Column("threshold_value", sa.Float(), nullable=False),
        sa.Column("time_window_minutes", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("severity", sa.Text(), nullable=False, server_default="major"),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notification_email", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
    )
    op.create_index("ix_alert_limits_organization_id", "alert_limits", ["organization_id"])
    op.create_index("ix_alert_limits_cluster_id", "alert_limits", ["cluster_id"])

    op.create_table(
        "alert_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cluster_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alert_limit_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("alert_limits.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=True),
        sa.Column("threshold_value", sa.Float(), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("notification_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notification_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_alert_events_organization_id", "alert_events", ["organization_id"])
    op.create_index("ix_alert_events_cluster_id", "alert_events", ["cluster_id"])
    op.create_index("ix_alert_events_alert_limit_id", "alert_events", ["alert_limit_id"])


def downgrade() -> None:
    for index_name in [
        "ix_alert_events_alert_limit_id",
        "ix_alert_events_cluster_id",
        "ix_alert_events_organization_id",
    ]:
        op.drop_index(index_name, table_name="alert_events")
    op.drop_table("alert_events")

    for index_name in [
        "ix_alert_limits_cluster_id",
        "ix_alert_limits_organization_id",
    ]:
        op.drop_index(index_name, table_name="alert_limits")
    op.drop_table("alert_limits")
