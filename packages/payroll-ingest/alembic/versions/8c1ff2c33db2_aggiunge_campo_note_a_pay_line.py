"""aggiunge campo note a pay_line

Revision ID: 8c1ff2c33db2
Revises: 1448de6b11e7
Create Date: 2026-07-14 14:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8c1ff2c33db2'
down_revision: Union[str, Sequence[str], None] = '1448de6b11e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('pay_line', sa.Column('note', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('pay_line', 'note')
