"""carts.batch_no (出游组内批次序号)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-07

变更：
- carts + batch_no(INTEGER, NOT NULL, 默认 0)：同一用户在同一出游采购组内的批次序号。
  0 表示尚未提交的草稿；提交时分配 >=1。start_date 到达后每次「提交即封板」递增下一批。
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("carts", sa.Column("batch_no", sa.Integer(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    op.drop_column("carts", "batch_no")
