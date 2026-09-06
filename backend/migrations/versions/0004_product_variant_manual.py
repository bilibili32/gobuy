"""手工商品增强：商品类型/备注/商品级图 + 条目颜色/确认采购，去唯一约束

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-04

变更：
- products: + category(VARCHAR120) + remark(TEXT) + image_data(TEXT)
- cart_items: + color(VARCHAR120) + purchase_confirmed(BOOLEAN NOT NULL default false)
- 删除 uq_cart_items_cart_product（同商品多颜色 = 同 product 多行，原约束会阻止）
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("category", sa.String(120), nullable=True))
    op.add_column("products", sa.Column("remark", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("image_data", sa.Text(), nullable=True))
    op.add_column("cart_items", sa.Column("color", sa.String(120), nullable=True))
    op.add_column(
        "cart_items",
        sa.Column("purchase_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.drop_constraint("uq_cart_items_cart_product", "cart_items", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint("uq_cart_items_cart_product", "cart_items", ["cart_id", "product_id"])
    op.drop_column("cart_items", "purchase_confirmed")
    op.drop_column("cart_items", "color")
    op.drop_column("products", "image_data")
    op.drop_column("products", "remark")
    op.drop_column("products", "category")
