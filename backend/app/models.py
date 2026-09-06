import enum
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Role(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"
    PURCHASER = "purchaser"


class CartStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    LOCKED = "locked"
    SUCCESS = "success"
    FAILED = "failed"


class GroupStatus(str, enum.Enum):
    OPEN = "open"
    COMPLETED = "completed"


# 出游采购组 与 用户（需求人）的多对多：采购员把用户拉进组 / 用户凭邀请码自助加入。
group_members = Table(
    "group_members",
    Base.metadata,
    Column("group_id", ForeignKey("procurement_groups.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)


class PriceGroup(Base):
    """价格算法分组：每组一套税率/汇率。用户归属某组后，其清单折算按该组参数（未指派 = 默认组）。"""

    __tablename__ = "price_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tax_rate: Mapped[float] = mapped_column(Float)
    exchange_rate_jpy_cny: Mapped[float] = mapped_column(Float)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    users: Mapped[list["User"]] = relationship(back_populates="price_group")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.USER)
    # 账号是否可用：停用（原「删除」的保护策略）后无法登录，数据保留可再启用。
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    # 价格算法分组归属（可空 = 默认组）。
    price_group_id: Mapped[int | None] = mapped_column(ForeignKey("price_groups.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    carts: Mapped[list["Cart"]] = relationship(back_populates="user")
    price_group: Mapped["PriceGroup | None"] = relationship(back_populates="users")
    # 作为需求人加入的出游采购组（多对多）。
    procurement_groups: Mapped[list["ProcurementGroup"]] = relationship(secondary=group_members, back_populates="members")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    # 商品类型（手工添加时填写，如 日用品/化妆品/电子 等，可空）。
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # 商品级备注（手工添加时填写：购买位置 / 平台攻略等，仅该商品本条记录展示）。
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 商品级图片（手工添加，浏览器端压缩后 dataURL）。放商品层而非条目层：
    # 同一商品多种颜色共享一张图，避免每条 CartItem 各存一份 base64。
    image_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_name: Mapped[str] = mapped_column(String(120))
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # 金额：price_cents 存「该币种下的最小计价单位」——CNY 为分，JPY 为円（整数）。
    price_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="CNY", server_default=text("'CNY'"))
    # 旧版兼容字段：当前统一按 price_cents=税前原价，并按价格组叠加税率计算含税价。
    tax_included: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    stock_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    items: Mapped[list["CartItem"]] = relationship(back_populates="product")


class Cart(Base):
    __tablename__ = "carts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # 出游采购组归属（可空）：用户提交清单时整单归入某个进行中的出游组。
    # 同一张清单同时只归属一个组；撤回/重开后清空可再选择其它组。
    group_id: Mapped[int | None] = mapped_column(ForeignKey("procurement_groups.id"), nullable=True, index=True)
    status: Mapped[CartStatus] = mapped_column(Enum(CartStatus), default=CartStatus.DRAFT, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user: Mapped[User] = relationship(back_populates="carts")
    group: Mapped["ProcurementGroup | None"] = relationship(back_populates="carts")
    items: Mapped[list["CartItem"]] = relationship(back_populates="cart", cascade="all, delete-orphan")
    events: Mapped[list["ProcurementEvent"]] = relationship(back_populates="cart", cascade="all, delete-orphan")


class CartItem(Base):
    __tablename__ = "cart_items"
    # 说明：不去掉 (cart_id, product_id) 唯一约束的话，同一次「变体批量添加」
    # （同商品不同颜色 = 同 product 多行）会撞唯一索引，所以此处不再定义唯一约束，
    # 由 0004 迁移删除原有 uq_cart_items_cart_product。

    id: Mapped[int] = mapped_column(primary_key=True)
    cart_id: Mapped[int] = mapped_column(ForeignKey("carts.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    # 变体规格：颜色/型号等（手工「变体行」填写，自由文本，可空=无变体）。同商品不同颜色=多条行。
    color: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # 采购员「确认采购」状态：采购人勾选；需求人页面只读展示。
    purchase_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # 采购侧备注：仅采购员/管理员可编辑，需求人只读可见；与需求人填写的 Product.remark 分开。
    procurement_remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 手工添加时可附带一张本地图片（dataURL，前端已压缩 ~50KB）；仅旧手工条目/无变体时会填，
    # 变体批量添加统一走 product.image_data（商品级一张图）。
    image_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purchased: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    cart: Mapped[Cart] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(back_populates="items")


class ProcurementGroup(Base):
    """出游采购组：采购员跨国出游的一次完整采购周期。

    采购员创建组（标题 + 出游日期区间），把需求人批量拉入（或凭 4 位邀请码自助加入）。
    需求人在组内提交的清单（Cart.group_id）整单归组，采购员据此逐项勾选「确认采购 / 已采购」。
    每个采购员累计最多创建 3 个组；end_date 到达后该组停止收单。
    """

    __tablename__ = "procurement_groups"
    __table_args__ = (UniqueConstraint("invite_code", name="uq_procurement_groups_invite_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    purchaser_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # 4 位数字自助入组邀请码（创建时随机生成，唯一）。
    invite_code: Mapped[str] = mapped_column(String(4))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[GroupStatus] = mapped_column(Enum(GroupStatus), default=GroupStatus.OPEN, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purchaser: Mapped["User"] = relationship()
    members: Mapped[list["User"]] = relationship(secondary=group_members, back_populates="procurement_groups")
    carts: Mapped[list["Cart"]] = relationship(back_populates="group")


class Setting(Base):
    """键值配置表：存放税率、汇率等可自行修改的参数。"""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)


class ProcurementEvent(Base):
    __tablename__ = "procurement_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    cart_id: Mapped[int] = mapped_column(ForeignKey("carts.id"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cart: Mapped[Cart] = relationship(back_populates="events")

