"""add cluster metric samples

Revision ID: 0004_cluster_metric_samples
Revises: 0003_alert_limits
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_cluster_metric_samples"
down_revision = "0003_alert_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cluster_metric_samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cluster_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("namespace", sa.Text(), nullable=True),
        sa.Column("resource_kind", sa.Text(), nullable=False),
        sa.Column("resource_name", sa.Text(), nullable=False),
        sa.Column("container_name", sa.Text(), nullable=True),
        sa.Column("node_name", sa.Text(), nullable=True),
        sa.Column("metric_name", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_cluster_metric_samples_organization_id", "cluster_metric_samples", ["organization_id"])
    op.create_index("ix_cluster_metric_samples_cluster_id", "cluster_metric_samples", ["cluster_id"])
    op.create_index("ix_cluster_metric_samples_collected_at", "cluster_metric_samples", ["collected_at"])


def downgrade() -> None:
    for index_name in [
        "ix_cluster_metric_samples_collected_at",
        "ix_cluster_metric_samples_cluster_id",
        "ix_cluster_metric_samples_organization_id",
    ]:
        op.drop_index(index_name, table_name="cluster_metric_samples")
    op.drop_table("cluster_metric_samples")
