"""出游采购组：批次 → 出游组（标题+日期区间+邀请码+组员），清单整单归组

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-04

变更：
- 新增 procurement_groups 表（purchaser 创建，标题/起止日期/4 位邀请码/状态）
- 新增 group_members 关联表（组 与 需求人 多对多）
- carts + group_id（提交时整单归入某组）
- 旧 procurement_batches / cart_items.batch_id 保留为孤儿表/孤儿列，不再被代码引用
  （已部署库不破坏历史数据；此版本起采购走「出游组」流程）
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 说明：枚举类型仅在 create_table 的列定义中声明（name="groupstatus"），由 alembic 建表时一并创建；
    # 不要先手动 op.execute / .create() 创建同名枚举，否则与建表内的隐式创建冲突（duplicate type）。
    op.create_table(
        "procurement_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("purchaser_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("invite_code", sa.String(4), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.Enum("OPEN", "COMPLETED", name="groupstatus"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("invite_code", name="uq_procurement_groups_invite_code"),
    )
    op.create_index("ix_procurement_groups_purchaser_id", "procurement_groups", ["purchaser_id"])
    op.create_index("ix_procurement_groups_status", "procurement_groups", ["status"])

    op.create_table(
        "group_members",
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("procurement_groups.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    )

    op.add_column("carts", sa.Column("group_id", sa.Integer(), sa.ForeignKey("procurement_groups.id"), nullable=True))
    op.create_index("ix_carts_group_id", "carts", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_carts_group_id", table_name="carts")
    op.drop_column("carts", "group_id")
    op.drop_table("group_members")
    op.drop_index("ix_procurement_groups_status", table_name="procurement_groups")
    op.drop_index("ix_procurement_groups_purchaser_id", table_name="procurement_groups")
    op.drop_table("procurement_groups")
    sa.Enum(name="groupstatus").drop(op.get_bind(), checkfirst=True)
