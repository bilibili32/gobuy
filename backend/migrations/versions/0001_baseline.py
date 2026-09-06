"""baseline schema

Revision ID: 0001
Revises:
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

role_enum = sa.Enum("ADMIN", "USER", "PURCHASER", name="role")
cartstatus_enum = sa.Enum("DRAFT", "SUBMITTED", "LOCKED", "SUCCESS", "FAILED", name="cartstatus")
batchstatus_enum = sa.Enum("OPEN", "COMPLETED", name="batchstatus")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", role_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_name", sa.String(length=120), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("image_url", sa.String(length=2048), nullable=True),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="CNY", nullable=False),
        sa.Column("tax_included", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("stock_count", sa.Integer(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_products_name", "products", ["name"])

    op.create_table(
        "carts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", cartstatus_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_carts_user_id", "carts", ["user_id"])
    op.create_index("ix_carts_status", "carts", ["status"])

    op.create_table(
        "procurement_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("purchaser_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", batchstatus_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_procurement_batches_status", "procurement_batches", ["status"])

    op.create_table(
        "cart_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cart_id", sa.Integer(), sa.ForeignKey("carts.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_cents", sa.Integer(), nullable=True),
        sa.Column("price_frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purchased", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("procurement_batches.id"), nullable=True),
        sa.UniqueConstraint("cart_id", "product_id", name="uq_cart_items_cart_product"),
    )
    op.create_index("ix_cart_items_cart_id", "cart_items", ["cart_id"])
    op.create_index("ix_cart_items_product_id", "cart_items", ["product_id"])

    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.String(length=255), nullable=False),
    )

    op.create_table(
        "procurement_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cart_id", sa.Integer(), sa.ForeignKey("carts.id"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_procurement_events_cart_id", "procurement_events", ["cart_id"])


def downgrade() -> None:
    op.drop_table("procurement_events")
    op.drop_table("settings")
    op.drop_table("cart_items")
    op.drop_table("procurement_batches")
    op.drop_table("carts")
    op.drop_table("products")
    op.drop_table("users")
    op.execute("DROP TYPE batchstatus")
    op.execute("DROP TYPE cartstatus")
    op.execute("DROP TYPE role")
