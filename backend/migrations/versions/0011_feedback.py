"""phase 6c: feedback (per user; Row Level Security like every per-user table)

Revision ID: 0011_feedback
Revises: 0010_macro_status_length
Create Date: 2026-10-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.types import UTCDateTime

revision: str = "0011_feedback"
down_revision: Union[str, Sequence[str], None] = "0010_macro_status_length"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

POLICY = ("current_setting('app.system', true) = 'on' "
          "OR user_id = NULLIF(current_setting('app.user_id', true), '')::integer")


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("page", sa.String(length=200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("done_at", UTCDateTime(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_feedback_created_at"), "feedback", ["created_at"], unique=False)
    op.create_index(op.f("ix_feedback_user_id"), "feedback", ["user_id"], unique=False)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE feedback ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE feedback FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON feedback USING ({POLICY}) WITH CHECK ({POLICY})")


def downgrade() -> None:
    op.drop_index(op.f("ix_feedback_user_id"), table_name="feedback")
    op.drop_index(op.f("ix_feedback_created_at"), table_name="feedback")
    op.drop_table("feedback")
