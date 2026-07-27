"""add_idempotency_key

Revision ID: d6650e411e45
Revises: c6b03d715b63
Create Date: 2026-07-27 11:58:22.379871

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision: str = 'd6650e411e45'
down_revision: Union[str, Sequence[str], None] = 'c6b03d715b63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use batch_alter_table for SQLite compatibility when altering tables
    with op.batch_alter_table('content_drafts', reflect_kwargs={'resolve_fks': False}) as batch_op:
        batch_op.add_column(sa.Column('idempotency_key', sa.String(length=100), nullable=True))
        batch_op.create_index(batch_op.f('ix_content_drafts_idempotency_key'), ['idempotency_key'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('content_drafts', reflect_kwargs={'resolve_fks': False}) as batch_op:
        batch_op.drop_index(batch_op.f('ix_content_drafts_idempotency_key'))
        batch_op.drop_column('idempotency_key')
