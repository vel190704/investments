"""macro_values.status: VARCHAR(10) -> VARCHAR(20) ("UNAVAILABLE" is 11 characters; Postgres enforces lengths)

Revision ID: 0010_macro_status_length
Revises: 0009_row_level_security
Create Date: 2026-10-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_macro_status_length"
down_revision: Union[str, Sequence[str], None] = "0009_row_level_security"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("macro_values") as b:
        b.alter_column("status", existing_type=sa.String(length=10), type_=sa.String(length=20),
                       existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("macro_values") as b:
        b.alter_column("status", existing_type=sa.String(length=20), type_=sa.String(length=10),
                       existing_nullable=False)
