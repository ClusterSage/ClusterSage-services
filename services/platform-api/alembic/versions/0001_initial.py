"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table("organizations", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("name", sa.Text(), nullable=False), *timestamps())
    op.create_table("users", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False), sa.Column("email", sa.Text(), unique=True, nullable=False), sa.Column("password_hash", sa.Text(), nullable=False), sa.Column("full_name", sa.Text(), nullable=True), sa.Column("role", sa.Text(), nullable=False, server_default="owner"), *timestamps())
    op.create_table("agent_keys", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False), sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True), sa.Column("name", sa.Text(), nullable=False), sa.Column("key_hash", sa.Text(), nullable=False), sa.Column("key_last4", sa.Text(), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True), sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("clusters", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False), sa.Column("name", sa.Text(), nullable=False), sa.Column("provider", sa.Text(), nullable=False, server_default="aks"), sa.Column("kube_system_uid", sa.Text(), nullable=True), sa.Column("agent_version", sa.Text(), nullable=True), sa.Column("status", sa.Text(), nullable=False, server_default="pending"), sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True), *timestamps(), sa.UniqueConstraint("organization_id", "name", name="uq_clusters_org_name"))
    op.create_table("log_batches", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False), sa.Column("cluster_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False), sa.Column("blob_path", sa.Text(), nullable=False), sa.Column("log_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"), sa.Column("start_time", sa.DateTime(timezone=True), nullable=True), sa.Column("end_time", sa.DateTime(timezone=True), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("cluster_snapshots", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False), sa.Column("cluster_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False), sa.Column("snapshot_type", sa.Text(), nullable=False), sa.Column("blob_path", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("issues", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False), sa.Column("cluster_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False), sa.Column("namespace", sa.Text(), nullable=True), sa.Column("workload", sa.Text(), nullable=True), sa.Column("pod_name", sa.Text(), nullable=True), sa.Column("severity", sa.Text(), nullable=False), sa.Column("issue_type", sa.Text(), nullable=False), sa.Column("title", sa.Text(), nullable=False), sa.Column("description", sa.Text(), nullable=True), sa.Column("status", sa.Text(), nullable=False, server_default="open"), sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("ai_recommendations", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False), sa.Column("cluster_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False), sa.Column("issue_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("issues.id", ondelete="SET NULL"), nullable=True), sa.Column("recommendation_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("audit_logs", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True), sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True), sa.Column("cluster_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clusters.id", ondelete="SET NULL"), nullable=True), sa.Column("action", sa.Text(), nullable=False), sa.Column("actor_type", sa.Text(), nullable=False), sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    for table in ["users", "agent_keys", "clusters", "log_batches", "cluster_snapshots", "issues", "audit_logs"]:
        op.create_index(f"ix_{table}_organization_id", table, ["organization_id"])


def downgrade() -> None:
    for table in ["audit_logs", "ai_recommendations", "issues", "cluster_snapshots", "log_batches", "clusters", "agent_keys", "users", "organizations"]:
        op.drop_table(table)
