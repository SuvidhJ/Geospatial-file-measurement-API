"""create files and features tables

Revision ID: 5691e2a8e587
Revises:
Create Date: 2026-10-11 22:00:01.604397
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5691e2a8e587"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "uploaded_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("crs", sa.Text(), nullable=True),
        sa.Column("crs_assumed", sa.Boolean(), nullable=False),
        sa.Column("feature_count", sa.Integer(), nullable=False),
        sa.Column("geometry_type_counts", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "features",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("source_fid", sa.Integer(), nullable=True),
        sa.Column("geometry_type", sa.String(length=32), nullable=True),
        sa.Column("measured_geometry_type", sa.String(length=32), nullable=True),
        sa.Column("geometry", sa.JSON(), nullable=True),
        sa.Column("geometry_crs", sa.Text(), nullable=True),
        sa.Column("source_crs", sa.Text(), nullable=True),
        sa.Column("properties", sa.JSON(), nullable=False),
        sa.Column("repaired", sa.Boolean(), nullable=False),
        sa.Column("measurement_status", sa.String(length=16), nullable=False),
        sa.Column("measurement_reason", sa.Text(), nullable=True),
        sa.Column("measurement_crs", sa.Text(), nullable=True),
        sa.Column("measurement_method", sa.String(length=32), nullable=True),
        sa.Column("area_m2", sa.Double(), nullable=True),
        sa.Column("perimeter_m", sa.Double(), nullable=True),
        sa.Column("length_m", sa.Double(), nullable=True),
        sa.Column("geodesic_area_m2", sa.Double(), nullable=True),
        sa.Column("geodesic_perimeter_m", sa.Double(), nullable=True),
        sa.Column("geodesic_length_m", sa.Double(), nullable=True),
        sa.Column("difference_pct", sa.Double(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["uploaded_files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id", "index"),
    )
    with op.batch_alter_table("features", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_features_file_id"), ["file_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_features_geometry_type"), ["geometry_type"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("features", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_features_geometry_type"))
        batch_op.drop_index(batch_op.f("ix_features_file_id"))

    op.drop_table("features")
    op.drop_table("uploaded_files")
