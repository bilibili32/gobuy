"""price groups + user active

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-04

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "price_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("tax_rate", sa.Float(), nullable=False),
        sa.Column("exchange_rate_jpy_cny", sa.Float(), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_index("ix_price_groups_name", "price_groups", ["name"], unique=True)

    # 默认组：初值继承旧 settings 表的全局税率/汇率（兼容管理员手工改过的值），无则 10 / 0.048。
    op.execute(
        "INSERT INTO price_groups (name, tax_rate, exchange_rate_jpy_cny, is_default) "
        "SELECT '默认组', "
        "COALESCE((SELECT value::float FROM settings WHERE key = 'tax_rate'), 10.0), "
        "COALESCE((SELECT value::float FROM settings WHERE key = 'exchange_rate_jpy_cny'), 0.048), true"
    )

    op.add_column("users", sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False))
    op.add_column("users", sa.Column("price_group_id", sa.Integer(), sa.ForeignKey("price_groups.id"), nullable=True))
    op.create_index("ix_users_price_group_id", "users", ["price_group_id"])


def downgrade() -> None:
    op.drop_index("ix_users_price_group_id", table_name="users")
    op.drop_column("users", "price_group_id")
    op.drop_column("users", "active")
    op.drop_table("price_groups")
