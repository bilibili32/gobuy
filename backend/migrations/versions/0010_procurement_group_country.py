"""procurement group country

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("procurement_groups", sa.Column("country", sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column("procurement_groups", "country")
