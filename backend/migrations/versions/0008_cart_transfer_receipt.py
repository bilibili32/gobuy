"""carts transfer number and receipt confirmation

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("carts", sa.Column("transfer_no", sa.String(length=120), nullable=True))
    op.add_column(
        "carts",
        sa.Column("receipt_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("carts", "receipt_confirmed")
    op.drop_column("carts", "transfer_no")
