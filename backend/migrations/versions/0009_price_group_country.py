"""price group country

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("price_groups", sa.Column("country", sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column("price_groups", "country")
