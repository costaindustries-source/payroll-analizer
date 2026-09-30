"""aggiunge le colonne del riepilogo annuale Copernico a tax e tfr

Revision ID: a4c1d7e93b52
Revises: 61f9220692dd
Create Date: 2026-09-30 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4c1d7e93b52'
down_revision: Union[str, Sequence[str], None] = '61f9220692dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TAX_COLUMNS = (
    'detrazioni_effettive_annue',
    'detrazioni_art13_annue',
    'detrazioni_altre_annue',
    'progr_gg_inps_annui',
    'progr_sett_inps_annue',
)
_TFR_COLUMNS = (
    'tfr_fondi_compl',
    'ctr_az_fondi_compl',
    'tfr_fondi_compl_ap',
    'tfr_fondi_compl_ac',
)


def upgrade() -> None:
    """Upgrade schema (solo colonne nullable: retrocompatibile)."""
    for column in _TAX_COLUMNS:
        op.add_column('tax', sa.Column(column, sa.Numeric(precision=14, scale=5), nullable=True))
    for column in _TFR_COLUMNS:
        op.add_column('tfr', sa.Column(column, sa.Numeric(precision=14, scale=5), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    for column in reversed(_TFR_COLUMNS):
        op.drop_column('tfr', column)
    for column in reversed(_TAX_COLUMNS):
        op.drop_column('tax', column)
