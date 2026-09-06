"""cart_items.procurement_remark (采购侧备注，仅采购员/管理员可编辑)

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-05

变更：
- cart_items + procurement_remark(TEXT, nullable)：采购员/管理员针对每条已提交商品填写的备注
  （如采购渠道、可用性、替代型号等），需求人只读可见。与需求人填写的 Product.remark 分开。
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cart_items", sa.Column("procurement_remark", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("cart_items", "procurement_remark")
