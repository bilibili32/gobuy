"""cart_items.image_data (manual item photo, dataURL)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-04

"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cart_items", sa.Column("image_data", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("cart_items", "image_data")
