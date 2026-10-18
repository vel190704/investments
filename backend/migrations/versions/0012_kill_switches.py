"""phase 6c: kill switches (users.disabled_at) and the admin audit log (global; RLS on, no policy, like every
global table, so Supabase's Data API roles read nothing)

Revision ID: 0012_kill_switches
Revises: 0011_feedback
Create Date: 2026-10-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.types import UTCDateTime

revision: str = "0012_kill_switches"
down_revision: Union[str, Sequence[str], None] = "0011_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("disabled_at", UTCDateTime(), nullable=True))
    op.create_table(
        "admin_audit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("at", UTCDateTime(), nullable=False),
        sa.Column("admin_user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_admin_audit_at"), "admin_audit", ["at"], unique=False)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE admin_audit ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index(op.f("ix_admin_audit_at"), table_name="admin_audit")
    op.drop_table("admin_audit")
    with op.batch_alter_table("users") as b:
        b.drop_column("disabled_at")
