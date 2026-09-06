import os
import random
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date, datetime, timezone
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import Select, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .db import SessionLocal, engine, get_session
from .kakaku import KakakuScraper, ProductDetail
from .kitamura import KITAMURA_HOSTS, KitamuraScraper
from .models import Cart, CartItem, CartStatus, GroupStatus, PriceGroup, ProcurementEvent, ProcurementGroup, Product, Role, Setting, User, group_members
from .security import create_access_token, decode_access_token, hash_password, verify_password


def parse_product_detail(url: str) -> ProductDetail:
    """按域名分发商品链接到对应站点解析器（kakaku / 北村相机）。

    各解析器内部自带 host 白名单与路径格式校验，防止 SSRF 与无关链接。
    """
    host = (urlparse(url).hostname or "").lower()
    if host in {"kakaku.com", "www.kakaku.com"}:
        return KakakuScraper(min_interval=0.0).parse_item_url(url)
    if host in KITAMURA_HOSTS:
        return KitamuraScraper(min_interval=0.0).parse_item_url(url)
    raise ValueError("仅支持 kakaku.com / kitamuracamera.jp（北村相机）商品详情页链接")


class RegisterRequest(BaseModel):
    email: str
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=128)


class LoginRequest(BaseModel):
    email: str
    password: str


class CartItemRequest(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1, le=1000)


class CartItemByUrlRequest(BaseModel):
    url: str
    quantity: int = Field(default=1, ge=1, le=1000)


class CartItemManualRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    price_yen: int = Field(ge=1)
    quantity: int = Field(default=1, ge=1, le=1000)
    # 可选商品图片：浏览器端压缩后的 dataURL（~50KB，base64 后约 68KB 字符）。
    image_data: str | None = Field(default=None, max_length=400_000)


class CartVariantRequest(BaseModel):
    """变体行：颜色/型号等规格（自由文本，可空=无变体）与数量。"""
    color: str | None = Field(default=None, max_length=120)
    quantity: int = Field(default=1, ge=1, le=1000)


class CartItemManualBatchRequest(BaseModel):
    """变体批量手工添加：一个商品(基础信息+图+备注) + N 个颜色/数量行。"""
    name: str = Field(min_length=1, max_length=255)
    price_yen: int = Field(ge=1)
    category: str | None = Field(default=None, max_length=120)
    remark: str | None = Field(default=None, max_length=2000)
    # 商品级图片 dataURL（浏览器压缩后）；同一商品所有变体共享这张图。
    image_data: str | None = Field(default=None, max_length=400_000)
    variants: list[CartVariantRequest] = Field(min_length=1, max_length=50)


class QuantityRequest(BaseModel):
    quantity: int = Field(ge=1, le=1000)


class CartSubmitRequest(BaseModel):
    """提交清单到出游组：用户同时属多个进行中组时必须指定 group_id，否则默认其唯一进行中组。"""
    group_id: int | None = None


class StatusRequest(BaseModel):
    status: CartStatus


class PurchasedRequest(BaseModel):
    purchased: bool


class ConfirmedRequest(BaseModel):
    confirmed: bool


class ProcurementRemarkRequest(BaseModel):
    remark: str | None = Field(default=None, max_length=2000)


class ParseUrlRequest(BaseModel):
    url: str


class ProductCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source_name: str = Field(min_length=1, max_length=120)
    source_url: str | None = Field(default=None, max_length=2048)
    image_url: str | None = Field(default=None, max_length=2048)
    price_cents: int = Field(ge=0)
    currency: str = Field(default="CNY", min_length=3, max_length=8)
    tax_included: bool = True
    stock_count: int | None = None
    category: str | None = Field(default=None, max_length=120)
    remark: str | None = Field(default=None, max_length=2000)


class ProductUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    price_cents: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    tax_included: bool | None = None
    stock_count: int | None = None
    category: str | None = Field(default=None, max_length=120)
    remark: str | None = Field(default=None, max_length=2000)


class SettingsRequest(BaseModel):
    tax_rate: float = Field(ge=0, le=100)
    exchange_rate_jpy_cny: float = Field(gt=0)


class GroupCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    start_date: date
    end_date: date


class GroupUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    start_date: date | None = None
    end_date: date | None = None
    status: GroupStatus | None = None


class GroupMembersRequest(BaseModel):
    user_ids: list[int] = Field(min_length=1)


class GroupJoinRequest(BaseModel):
    invite_code: str = Field(min_length=4, max_length=4)


class RoleRequest(BaseModel):
    role: Role


class AdminCreateUserRequest(BaseModel):
    email: str
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=6, max_length=128)
    role: Role = Role.USER
    price_group_id: int | None = None


class AdminPasswordRequest(BaseModel):
    password: str = Field(min_length=6, max_length=128)


class ActiveRequest(BaseModel):
    active: bool


class PriceGroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    tax_rate: float = Field(ge=0, le=100)
    exchange_rate_jpy_cny: float = Field(gt=0)


class PriceGroupMembershipRequest(BaseModel):
    price_group_id: int | None = None


class RegistrationRequest(BaseModel):
    allow_registration: bool


bearer = HTTPBearer()


# 运行时缓存（单进程部署，管理员改设置后即时生效，无需跨进程同步）。
# PRICE_GROUPS: 价格组 id -> 参数；DEFAULT_GROUP_ID: 默认组 id；REGISTRATION_OPEN: 是否允许自助注册。
PRICE_GROUPS: dict[int, dict[str, float]] = {}
DEFAULT_GROUP_ID: int | None = None
REGISTRATION_OPEN: bool = True
_FALLBACK_PARAMS: dict[str, float] = {"tax_rate": 10.0, "exchange_rate_jpy_cny": 0.048}


async def refresh_runtime_settings() -> None:
    """从数据库读回价格组与注册开关，覆盖进程内缓存。"""
    global DEFAULT_GROUP_ID, REGISTRATION_OPEN
    async with SessionLocal() as session:
        groups = (await session.execute(select(PriceGroup))).scalars().all()
        PRICE_GROUPS.clear()
        for group in groups:
            PRICE_GROUPS[group.id] = {
                "name": group.name,
                "tax_rate": group.tax_rate,
                "exchange_rate_jpy_cny": group.exchange_rate_jpy_cny,
            }
            if group.is_default:
                DEFAULT_GROUP_ID = group.id
        reg = await session.get(Setting, "allow_registration")
        REGISTRATION_OPEN = reg is None or reg.value not in ("0", "false", "off")


def _group_params(group_id: int | None) -> dict[str, float]:
    """取某价格组参数；无归属 / 组不存在时回退默认组，再回退内置常量。"""
    if group_id is not None and group_id in PRICE_GROUPS:
        return PRICE_GROUPS[group_id]
    if DEFAULT_GROUP_ID is not None and DEFAULT_GROUP_ID in PRICE_GROUPS:
        return PRICE_GROUPS[DEFAULT_GROUP_ID]
    return _FALLBACK_PARAMS


def default_params() -> dict[str, float]:
    """默认组参数（无归属商品的浏览 / 商品库场景）。"""
    return _group_params(None)


def effective_price(price_cents: int, currency: str, tax_included: bool, params: dict[str, float] | None = None) -> dict[str, int]:
    """按统一的税前原价口径计算税前价、含税价和人民币价。

    ``price_cents`` 始终是商品添加时录入的税前原价：
    - 税前价 = 原价；
    - 含税价 = 原价 × (1 + 税率)；
    - 人民币价统一按含税价折算。

    ``tax_included`` 保留为旧版 API/数据库字段，避免已有客户端和数据结构不兼容；
    新价格展示不再根据该旧标记反推或覆盖原价。JPY 以日元为最小单位，CNY 以分为最小单位。
    """
    del tax_included  # 兼容旧调用，当前产品统一按税前原价计算。
    p = params or default_params()
    pretax = price_cents
    taxed = round(price_cents * (1 + p["tax_rate"] / 100.0))
    if currency == "JPY":
        cny = round(taxed * p["exchange_rate_jpy_cny"] * 100)
    else:
        cny = taxed
    return {"pretax_price_cents": pretax, "taxed_price_cents": taxed, "price_cny_cents": cny}


def product_payload(product: Product, params: dict[str, float] | None = None) -> dict:
    calc = effective_price(product.price_cents, product.currency, product.tax_included, params)
    return {
        "id": product.id,
        "name": product.name,
        "category": product.category,
        "remark": product.remark,
        "source_name": product.source_name,
        "source_url": product.source_url,
        "image_url": product.image_url,
        "price_cents": product.price_cents,
        "currency": product.currency,
        "tax_included": product.tax_included,
        "pretax_price_cents": calc["pretax_price_cents"],
        "taxed_price_cents": calc["taxed_price_cents"],
        "price_cny_cents": calc["price_cny_cents"],
        "stock_count": product.stock_count,
        "synced_at": product.synced_at,
    }


def _item_price(item: CartItem) -> int:
    return item.unit_price_cents if item.unit_price_cents is not None else item.product.price_cents


def cart_payload(cart: Cart) -> dict:
    # 折算参数取「清单归属用户」的价格组：同一张单，提交人与审批人看到的金额一致。
    params = _group_params(cart.user.price_group_id if cart.user else None)
    items = []
    for item in cart.items:
        calc = effective_price(_item_price(item), item.product.currency, item.product.tax_included, params)
        items.append(
            {
                "id": item.id,
                "quantity": item.quantity,
                "color": item.color,
                "purchase_confirmed": item.purchase_confirmed,
                "procurement_remark": item.procurement_remark,
                "unit_price_cents": _item_price(item),
                "price_frozen": item.price_frozen_at is not None,
                "purchased": item.purchased,
                # 图片优先条目级（旧手工单条），否则取商品级图（变体批量，全组共享一张）。
                "image_data": item.image_data or item.product.image_data,
                "pretax_price_cents": calc["pretax_price_cents"],
                "taxed_price_cents": calc["taxed_price_cents"],
                "price_cny_cents": calc["price_cny_cents"],
                "product": product_payload(item.product, params),
            }
        )
    group = cart.group
    return {
        "id": cart.id,
        "user": {"id": cart.user.id, "email": cart.user.email, "full_name": cart.user.full_name},
        "group": {"id": group.id, "title": group.title} if group else None,
        "status": cart.status.value,
        "created_at": cart.created_at,
        "submitted_at": cart.submitted_at,
        "locked_at": cart.locked_at,
        "items": items,
    }


# 出游采购组：采购员建组（标题+出游日期区间+4位邀请码），批量拉需求人/自助入组；
# 需求人提交清单整单归组（Cart.group_id），采购员组内逐项勾选「确认采购 / 已采购」。


def _group_select() -> Select:
    return select(ProcurementGroup).options(
        selectinload(ProcurementGroup.purchaser),
        selectinload(ProcurementGroup.members),
    )


def _group_detail_select() -> Select:
    return select(ProcurementGroup).options(
        selectinload(ProcurementGroup.purchaser),
        selectinload(ProcurementGroup.members),
        selectinload(ProcurementGroup.carts)
        .selectinload(Cart.items)
        .selectinload(CartItem.product),
        selectinload(ProcurementGroup.carts).selectinload(Cart.user),
    )


async def load_group(session: AsyncSession, group_id: int, for_update: bool = False, detail: bool = False) -> ProcurementGroup | None:
    statement = (_group_detail_select() if detail else _group_select()).where(ProcurementGroup.id == group_id)
    if for_update:
        statement = statement.with_for_update()
    # populate_existing：同一会话内反复 load 同一实例时，强制从 DB 刷新列与关系
    # （含 cart.group / group.members 等），避免 identity map 陈旧缓存导致返回过期数据。
    statement = statement.execution_options(populate_existing=True)
    return (await session.execute(statement)).scalar_one_or_none()


def member_payload(user: User) -> dict:
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "active": user.active}


def group_payload(group: ProcurementGroup) -> dict:
    """组的基础信息 + 成员列表（不含条目，列表页用）。"""
    return {
        "id": group.id,
        "title": group.title,
        "status": group.status.value,
        "invite_code": group.invite_code,
        "start_date": group.start_date.isoformat(),
        "end_date": group.end_date.isoformat(),
        "created_at": group.created_at,
        "completed_at": group.completed_at,
        "purchaser": member_payload(group.purchaser),
        "members": [member_payload(m) for m in group.members],
        "member_count": len(group.members),
    }


def group_detail_payload(group: ProcurementGroup) -> dict:
    """组详情：基础信息 + 成员 + 组内已归组清单的条目（采购员勾选用）。

    只聚合非草稿（submitted/locked/failed/success）且 Cart.group_id == 本组的清单；
    草稿尚未提交不显示（提交时才整单归组）。
    """
    base = group_payload(group)
    items = []
    for cart in group.carts:
        if cart.status == CartStatus.DRAFT:
            continue
        params = _group_params(cart.user.price_group_id if cart.user else None)
        for item in cart.items:
            calc = effective_price(_item_price(item), item.product.currency, item.product.tax_included, params)
            items.append(
                {
                    "id": item.id,
                    "cart_id": cart.id,
                    "cart_status": cart.status.value,
                    "quantity": item.quantity,
                    "color": item.color,
                    "purchase_confirmed": item.purchase_confirmed,
                    "procurement_remark": item.procurement_remark,
                    "purchased": item.purchased,
                    "unit_price_cents": _item_price(item),
                    "image_data": item.image_data or item.product.image_data,
                    "pretax_price_cents": calc["pretax_price_cents"],
                    "taxed_price_cents": calc["taxed_price_cents"],
                    "price_cny_cents": calc["price_cny_cents"],
                    "product": product_payload(item.product, params),
                    "requester": {
                        "id": cart.user.id,
                        "full_name": cart.user.full_name,
                        "email": cart.user.email,
                    },
                }
            )
    base["items"] = items
    base["total"] = len(items)
    base["purchased"] = sum(1 for i in items if i["purchased"])
    return base


def _default_group_name() -> str:
    return str(default_params().get("name", "默认组"))


def user_payload(user: User, cart_count: int | None = None) -> dict:
    """用户信息（me / 管理列表通用）。只读列与缓存，不触发 ORM 懒加载。"""
    payload = {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role.value,
        "active": user.active,
        "price_group_id": user.price_group_id,
        "price_group_name": PRICE_GROUPS.get(user.price_group_id, {}).get("name", _default_group_name())
        if user.price_group_id
        else _default_group_name(),
        "created_at": user.created_at,
    }
    if cart_count is not None:
        payload["cart_count"] = cart_count
    return payload


# 状态机：允许的状态跳转。
# draft -> submitted -> locked -> success / failed
# 附加：用户撤回(submitted->draft)、管理员解锁(locked->submitted)、失败退回(failed->draft)。
CART_TRANSITIONS: dict[CartStatus, set[CartStatus]] = {
    CartStatus.DRAFT: {CartStatus.SUBMITTED},
    CartStatus.SUBMITTED: {CartStatus.DRAFT, CartStatus.LOCKED, CartStatus.FAILED},
    CartStatus.LOCKED: {CartStatus.SUBMITTED, CartStatus.SUCCESS, CartStatus.FAILED},
    CartStatus.SUCCESS: set(),
    CartStatus.FAILED: {CartStatus.DRAFT},
}


def apply_status_change(cart: Cart, new_status: CartStatus) -> None:
    if new_status not in CART_TRANSITIONS[cart.status]:
        raise HTTPException(status_code=409, detail=f"Cannot change {cart.status.value} to {new_status.value}")
    cart.status = new_status
    if new_status == CartStatus.LOCKED:
        cart.locked_at = datetime.now(timezone.utc)
        # 锁定时冻结单价，此后商品改价不影响本采购单
        for item in cart.items:
            item.unit_price_cents = item.product.price_cents
            item.price_frozen_at = cart.locked_at
    elif new_status in (CartStatus.DRAFT, CartStatus.SUBMITTED):
        # 回到可编辑/待处理状态时，恢复为实时价格
        for item in cart.items:
            item.unit_price_cents = None
            item.price_frozen_at = None


async def load_cart(session: AsyncSession, cart_id: int, for_update: bool = False) -> Cart | None:
    statement: Select = (
        select(Cart)
        .where(Cart.id == cart_id)
        .options(
            selectinload(Cart.user),
            selectinload(Cart.group),
            selectinload(Cart.items).selectinload(CartItem.product),
        )
    )
    if for_update:
        statement = statement.with_for_update()
    # populate_existing：同一会话内反复 load 同一实例时，强制从 DB 刷新列与关系
    # （含 cart.group / group.members 等），避免 identity map 陈旧缓存导致返回过期数据。
    statement = statement.execution_options(populate_existing=True)
    return (await session.execute(statement)).scalar_one_or_none()


async def draft_cart(session: AsyncSession, user_id: int) -> Cart:
    statement = select(Cart).where(Cart.user_id == user_id, Cart.status == CartStatus.DRAFT).order_by(Cart.id.desc())
    cart = (await session.execute(statement)).scalars().first()
    if cart:
        return cart
    cart = Cart(user_id=user_id, status=CartStatus.DRAFT)
    session.add(cart)
    await session.flush()
    return cart


async def user_open_groups(session: AsyncSession, user_id: int) -> list[ProcurementGroup]:
    """当前用户可提交的出游组：进行中(open) 且 未过 end_date（到达结束日期后停止收单）。"""
    today = date.today()
    statement = (
        select(ProcurementGroup)
        .join(group_members, group_members.c.group_id == ProcurementGroup.id)
        .where(
            group_members.c.user_id == user_id,
            ProcurementGroup.status == GroupStatus.OPEN,
            ProcurementGroup.end_date >= today,
        )
        .options(selectinload(ProcurementGroup.purchaser), selectinload(ProcurementGroup.members))
        .order_by(ProcurementGroup.end_date.asc())
    )
    return list((await session.execute(statement)).scalars().all())


async def current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    try:
        user_id = int(decode_access_token(credentials.credentials)["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not user.active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用，请联系管理员")
    return user


async def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != Role.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator permission required")
    return user


async def price_manager_user(user: User = Depends(current_user)) -> User:
    """价格分组维护权限：管理员与采购员均可增删改（普通用户只读）。"""
    if user.role not in (Role.ADMIN, Role.PURCHASER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有管理员或采购员可以维护价格分组")
    return user


async def seed_data() -> None:
    products = [
        ("USB-C 扩展坞 12 合 1", "TechSource", 64900, 38),
        ("27 英寸 4K 显示器", "Office Mall", 189900, 12),
        ("2TB 固态硬盘", "DataParts", 84900, 21),
        ("CAT6A 网线套装", "Network Pro", 7700, 28),
    ]
    async with SessionLocal() as session:
        if not (await session.execute(select(Product.id).limit(1))).first():
            session.add_all(
                [Product(name=name, source_name=source, price_cents=price, stock_count=stock) for name, source, price, stock in products]
            )
        email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
        password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
        if email and password and not (await session.execute(select(User).where(User.email == email))).scalar_one_or_none():
            session.add(User(email=email, full_name="系统管理员", password_hash=hash_password(password), role=Role.ADMIN))
        if not (await session.get(Setting, "allow_registration")):
            session.add(Setting(key="allow_registration", value="1"))
        # 兜底：确保存在一个默认价格组（正常由 Alembic 0002 迁移创建）。
        default_group = (await session.execute(select(PriceGroup).where(PriceGroup.is_default.is_(True)))).scalar_one_or_none()
        if not default_group and not (await session.execute(select(PriceGroup.id).limit(1))).first():
            session.add(PriceGroup(name="默认组", tax_rate=10.0, exchange_rate_jpy_cny=0.048, is_default=True))
        await session.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 表结构由 Alembic 迁移管理（容器启动时 `alembic upgrade head`），这里只做数据种子与缓存初始化。
    await seed_data()
    await refresh_runtime_settings()
    yield
    await engine.dispose()


app = FastAPI(title="买办 Procurement API", version="0.1.0", lifespan=lifespan)
origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:8080").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/auth/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, session: AsyncSession = Depends(get_session)) -> dict:
    if not REGISTRATION_OPEN:
        raise HTTPException(status_code=403, detail="注册已关闭，请联系管理员开通账号")
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="A valid email address is required")
    if (await session.execute(select(User).where(User.email == email))).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email is already registered")
    user = User(email=email, full_name=body.full_name.strip(), password_hash=hash_password(body.password), role=Role.USER)
    session.add(user)
    await session.commit()
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role.value}


@app.post("/api/auth/login")
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)) -> dict:
    user = (await session.execute(select(User).where(User.email == body.email.strip().lower()))).scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    if not user.active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用，请联系管理员")
    return {"access_token": create_access_token(user.id, user.role.value), "token_type": "bearer", "role": user.role.value}


@app.get("/api/users/me")
async def me(user: User = Depends(current_user)) -> dict:
    return user_payload(user)


@app.get("/api/products")
async def list_products(q: str | None = Query(default=None, max_length=120), _: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> list[dict]:
    statement = select(Product).order_by(Product.name)
    if q:
        term = f"%{q.strip()}%"
        statement = statement.where(or_(Product.name.ilike(term), Product.source_name.ilike(term)))
    return [product_payload(product) for product in (await session.execute(statement)).scalars().all()]


@app.post("/api/products/parse-url")
async def parse_product_url(body: ParseUrlRequest, _: User = Depends(current_user)) -> dict:
    """解析用户粘贴的商品详情页链接（kakaku / 北村相机），返回名称/价格/缩略图。"""
    try:
        detail = parse_product_detail(body.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=502, detail="链接解析失败，请确认是 kakaku.com / kitamuracamera.jp 商品详情页且网络可达")
    return asdict(detail)


@app.post("/api/products", status_code=status.HTTP_201_CREATED)
async def create_product(body: ProductCreateRequest, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> dict:
    if body.source_url:
        existing = (await session.execute(select(Product).where(Product.source_url == body.source_url))).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="该商品已存在于商品库")
    product = Product(
        name=body.name.strip(),
        category=body.category.strip() if body.category and body.category.strip() else None,
        remark=body.remark.strip() if body.remark and body.remark.strip() else None,
        source_name=body.source_name.strip(),
        source_url=body.source_url,
        image_url=body.image_url,
        price_cents=body.price_cents,
        currency=body.currency.upper(),
        tax_included=body.tax_included,
        stock_count=body.stock_count,
    )
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product_payload(product)


@app.patch("/api/products/{product_id}")
async def update_product(product_id: int, body: ProductUpdateRequest, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> dict:
    product = await session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    updates = body.model_dump(exclude_unset=True)
    if "name" in updates:
        product.name = updates["name"].strip()
    if "category" in updates:
        product.category = updates["category"].strip() if updates["category"] and updates["category"].strip() else None
    if "remark" in updates:
        product.remark = updates["remark"].strip() if updates["remark"] and updates["remark"].strip() else None
    if "price_cents" in updates:
        product.price_cents = updates["price_cents"]
    if "currency" in updates:
        product.currency = updates["currency"].upper()
    if "tax_included" in updates:
        product.tax_included = updates["tax_included"]
    if "stock_count" in updates:
        product.stock_count = updates["stock_count"]
    await session.commit()
    await session.refresh(product)
    return product_payload(product)


@app.delete("/api/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: int, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> None:
    product = await session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    referenced = (await session.execute(select(CartItem.id).where(CartItem.product_id == product_id).limit(1))).first()
    if referenced:
        raise HTTPException(status_code=409, detail="该商品已被加入清单，无法删除")
    await session.delete(product)
    await session.commit()


@app.get("/api/settings/price")
async def get_price_settings(_: User = Depends(current_user)) -> dict:
    """返回默认价格组的税率与基础汇率（无归属场景/前端展示用）。"""
    p = default_params()
    return {"tax_rate": p["tax_rate"], "exchange_rate_jpy_cny": p["exchange_rate_jpy_cny"]}


@app.put("/api/settings/price")
async def update_price_settings(body: SettingsRequest, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> dict:
    """修改默认价格组的税率 / 汇率（等价于旧版全局参数）。"""
    group = (await session.execute(select(PriceGroup).where(PriceGroup.is_default.is_(True)))).scalar_one()
    group.tax_rate = body.tax_rate
    group.exchange_rate_jpy_cny = body.exchange_rate_jpy_cny
    await session.commit()
    await refresh_runtime_settings()
    p = default_params()
    return {"tax_rate": p["tax_rate"], "exchange_rate_jpy_cny": p["exchange_rate_jpy_cny"]}


@app.get("/api/carts/me")
async def get_my_cart(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    # 当前清单 = 最新的非 success 清单，供用户在提交/锁定/失败后仍能看到自己的请求状态；
    # 仅当最新清单已 success，或尚无清单时，才开启一张新草稿。
    statement = select(Cart).where(Cart.user_id == user.id).order_by(Cart.id.desc())
    latest = (await session.execute(statement)).scalars().first()
    cart = latest if latest and latest.status != CartStatus.SUCCESS else None
    if cart is None:
        cart = Cart(user_id=user.id, status=CartStatus.DRAFT)
        session.add(cart)
        await session.flush()
    await session.commit()
    return cart_payload(await load_cart(session, cart.id))


@app.post("/api/carts/me/items", status_code=status.HTTP_201_CREATED)
async def add_cart_item(body: CartItemRequest, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    product = await session.get(Product, body.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    cart = await draft_cart(session, user.id)
    item = (await session.execute(select(CartItem).where(CartItem.cart_id == cart.id, CartItem.product_id == product.id))).scalar_one_or_none()
    if item:
        item.quantity += body.quantity
    else:
        session.add(CartItem(cart_id=cart.id, product_id=product.id, quantity=body.quantity))
    await session.commit()
    return cart_payload(await load_cart(session, cart.id))


@app.post("/api/carts/me/items/by-url", status_code=status.HTTP_201_CREATED)
async def add_cart_item_by_url(body: CartItemByUrlRequest, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """解析粘贴的商品链接：商品不在库则自动入库，再加入当前草稿清单。"""
    try:
        detail = parse_product_detail(body.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=502, detail="链接解析失败，请确认是 kakaku.com / kitamuracamera.jp 商品详情页且网络可达")
    if detail.price_yen is None:
        raise HTTPException(status_code=422, detail="未能解析出商品价格，请确认链接正确")
    product = (await session.execute(select(Product).where(Product.source_url == detail.url))).scalar_one_or_none()
    if not product:
        product = Product(
            name=detail.name,
            source_name=detail.source,
            source_url=detail.url,
            image_url=detail.image_url,
            price_cents=detail.price_yen,
            currency="JPY",
            tax_included=True,
        )
        session.add(product)
        await session.flush()
    cart = await draft_cart(session, user.id)
    item = (await session.execute(select(CartItem).where(CartItem.cart_id == cart.id, CartItem.product_id == product.id))).scalar_one_or_none()
    if item:
        item.quantity += body.quantity
    else:
        session.add(CartItem(cart_id=cart.id, product_id=product.id, quantity=body.quantity))
    await session.commit()
    return cart_payload(await load_cart(session, cart.id))


@app.post("/api/carts/me/items/manual", status_code=status.HTTP_201_CREATED)
async def add_cart_item_manual(body: CartItemManualRequest, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """手工添加商品：按名称/价格(日元)/数量直接加入当前草稿清单。"""
    product = Product(
        name=body.name.strip(),
        source_name="手工添加",
        price_cents=body.price_yen,
        currency="JPY",
        tax_included=True,
    )
    session.add(product)
    await session.flush()
    cart = await draft_cart(session, user.id)
    item = CartItem(cart_id=cart.id, product_id=product.id, quantity=body.quantity, image_data=body.image_data)
    session.add(item)
    await session.commit()
    return cart_payload(await load_cart(session, cart.id))


@app.post("/api/carts/me/items/manual-batch", status_code=status.HTTP_201_CREATED)
async def add_cart_item_manual_batch(body: CartItemManualBatchRequest, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """变体批量手工添加：一个商品基础信息（名称/类型/单价/备注/商品级图）+ N 个颜色数量行。

    一次调用创建 1 个 Product 与 N 条 CartItem（同一 product_id、不同 color），
    展示端按 product_id 分组为「商品组头 + 颜色子行」。
    """
    product = Product(
        name=body.name.strip(),
        category=body.category.strip() if body.category and body.category.strip() else None,
        remark=body.remark.strip() if body.remark and body.remark.strip() else None,
        image_data=body.image_data,
        source_name="手工添加",
        price_cents=body.price_yen,
        currency="JPY",
        tax_included=True,
    )
    session.add(product)
    await session.flush()
    cart = await draft_cart(session, user.id)
    for variant in body.variants:
        color = variant.color.strip() if variant.color and variant.color.strip() else None
        session.add(
            CartItem(
                cart_id=cart.id,
                product_id=product.id,
                quantity=variant.quantity,
                color=color,
            )
        )
    await session.commit()
    return cart_payload(await load_cart(session, cart.id))


@app.patch("/api/carts/me/items/{item_id}")
async def update_my_item(item_id: int, body: QuantityRequest, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    item = (await session.execute(select(CartItem).join(Cart).where(CartItem.id == item_id, Cart.user_id == user.id, Cart.status == CartStatus.DRAFT))).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Editable cart item not found")
    item.quantity = body.quantity
    await session.commit()
    return cart_payload(await load_cart(session, item.cart_id))


@app.delete("/api/carts/me/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_item(item_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> None:
    item = (await session.execute(select(CartItem).join(Cart).where(CartItem.id == item_id, Cart.user_id == user.id, Cart.status == CartStatus.DRAFT))).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Editable cart item not found")
    await session.delete(item)
    await session.commit()


@app.post("/api/carts/me/submit")
async def submit_my_cart(body: CartSubmitRequest | None = None, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """提交清单：整单归入一个出游采购组。

    - 用户属于 1 个进行中（未过 end_date）组 → 默认归该组；
    - 属于多个 → 必须显式传 group_id（属于其一）；
    - 不属于任何进行中组 → 422 提示先加入出游组。
    body 可省略（默认 group_id=None），兼容旧客户端直接 POST。
    """
    groups = await user_open_groups(session, user.id)
    if not groups:
        raise HTTPException(status_code=422, detail="你还没有加入进行中的出游采购组，请先联系采购员加入或输入邀请码")
    target_id = body.group_id if body else None
    if target_id is None:
        if len(groups) > 1:
            raise HTTPException(status_code=422, detail="你同时在多个进行中的出游组，请选择要提交给的组")
        target_id = groups[0].id
    if target_id not in {g.id for g in groups}:
        raise HTTPException(status_code=403, detail="只能提交给自己加入的进行中出游组")
    cart = await draft_cart(session, user.id)
    cart = await load_cart(session, cart.id, for_update=True)
    if not cart.items:
        raise HTTPException(status_code=422, detail="Cart must contain at least one item")
    cart.group_id = target_id
    cart.status = CartStatus.SUBMITTED
    cart.submitted_at = datetime.now(timezone.utc)
    session.add(ProcurementEvent(cart_id=cart.id, actor_id=user.id, event_type="submitted", details=f"group:{target_id}"))
    await session.commit()
    return cart_payload(await load_cart(session, cart.id))


@app.post("/api/carts/me/withdraw")
async def withdraw_my_cart(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    statement = select(Cart.id).where(Cart.user_id == user.id, Cart.status == CartStatus.SUBMITTED).order_by(Cart.id.desc())
    cart_id = (await session.execute(statement)).scalars().first()
    if cart_id is None:
        raise HTTPException(status_code=404, detail="No submitted cart to withdraw")
    cart = await load_cart(session, cart_id, for_update=True)
    apply_status_change(cart, CartStatus.DRAFT)
    cart.group_id = None
    session.add(ProcurementEvent(cart_id=cart.id, actor_id=user.id, event_type="withdrawn"))
    await session.commit()
    return cart_payload(await load_cart(session, cart.id))


@app.post("/api/carts/me/reopen")
async def reopen_my_cart(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    statement = select(Cart.id).where(Cart.user_id == user.id, Cart.status == CartStatus.FAILED).order_by(Cart.id.desc())
    cart_id = (await session.execute(statement)).scalars().first()
    if cart_id is None:
        raise HTTPException(status_code=404, detail="No failed cart to reopen")
    cart = await load_cart(session, cart_id, for_update=True)
    apply_status_change(cart, CartStatus.DRAFT)
    cart.group_id = None
    session.add(ProcurementEvent(cart_id=cart.id, actor_id=user.id, event_type="reopened"))
    await session.commit()
    return cart_payload(await load_cart(session, cart.id))


@app.get("/api/admin/carts")
async def admin_carts(status_filter: CartStatus | None = Query(default=None, alias="status"), user_id: int | None = Query(default=None), _: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> list[dict]:
    statement = (
        select(Cart)
        .options(
            selectinload(Cart.user),
            selectinload(Cart.group),
            selectinload(Cart.items).selectinload(CartItem.product),
        )
        .order_by(Cart.updated_at.desc())
    )
    if user_id:
        # 管理员查看某个用户的全部清单（含草稿态），点击头像进入时用。
        statement = statement.where(Cart.user_id == user_id)
    elif status_filter:
        statement = statement.where(Cart.status == status_filter)
    else:
        statement = statement.where(Cart.status != CartStatus.DRAFT)
    return [cart_payload(cart) for cart in (await session.execute(statement)).scalars().all()]


@app.patch("/api/admin/cart-items/{item_id}")
async def admin_update_item(item_id: int, body: QuantityRequest, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> dict:
    item = await session.get(CartItem, item_id, with_for_update=True)
    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found")
    item.quantity = body.quantity
    session.add(ProcurementEvent(cart_id=item.cart_id, actor_id=admin.id, event_type="item_quantity_changed", details=str(body.quantity)))
    await session.commit()
    return cart_payload(await load_cart(session, item.cart_id))


@app.patch("/api/admin/cart-items/{item_id}/purchased")
async def admin_toggle_purchased(item_id: int, body: PurchasedRequest, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """标记条目已采购：管理员可操作任意条目；采购人仅能操作自己创建出游组内的条目。"""
    item = (
        await session.execute(
            select(CartItem)
            .options(selectinload(CartItem.cart).selectinload(Cart.group))
            .where(CartItem.id == item_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found")
    if user.role != Role.ADMIN:
        group = item.cart.group if item.cart else None
        if user.role != Role.PURCHASER or group is None or group.purchaser_id != user.id:
            raise HTTPException(status_code=403, detail="只能标记自己创建的出游组内的条目")
    item.purchased = body.purchased
    session.add(ProcurementEvent(cart_id=item.cart_id, actor_id=user.id, event_type="item_purchased" if body.purchased else "item_purchase_undone", details=str(body.purchased)))
    await session.commit()
    return cart_payload(await load_cart(session, item.cart_id))


@app.patch("/api/admin/cart-items/{item_id}/confirmed")
async def admin_toggle_confirmed(item_id: int, body: ConfirmedRequest, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """标记条目「确认采购」：采购员的备忘勾选，防买重。

    权限与 purchased 一致：管理员可操作任意条目；采购人仅能操作自己创建出游组内的条目。
    需求人（普通用户）侧只读展示，无法修改 → 走本端点会 403。
    """
    item = (
        await session.execute(
            select(CartItem)
            .options(selectinload(CartItem.cart).selectinload(Cart.group))
            .where(CartItem.id == item_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found")
    if user.role != Role.ADMIN:
        group = item.cart.group if item.cart else None
        if user.role != Role.PURCHASER or group is None or group.purchaser_id != user.id:
            raise HTTPException(status_code=403, detail="只能标记自己创建的出游组内的条目")
    item.purchase_confirmed = body.confirmed
    session.add(ProcurementEvent(cart_id=item.cart_id, actor_id=user.id, event_type="item_confirmed" if body.confirmed else "item_confirmed_undone", details=str(body.confirmed)))
    await session.commit()
    return cart_payload(await load_cart(session, item.cart_id))


@app.patch("/api/admin/cart-items/{item_id}/remark")
async def admin_update_remark(item_id: int, body: ProcurementRemarkRequest, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """更新条目「采购侧备注」：采购员/管理员可编辑自己组内/任意条目的备注。

    权限与 confirmed / purchased 一致：管理员可操作任意条目；采购人仅能操作自己创建出游组内的条目；
    需求人（普通用户）调本端点会 403 —— 只能在前端只读看到该备注。
    """
    item = (
        await session.execute(
            select(CartItem)
            .options(selectinload(CartItem.cart).selectinload(Cart.group))
            .where(CartItem.id == item_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found")
    if user.role != Role.ADMIN:
        group = item.cart.group if item.cart else None
        if user.role != Role.PURCHASER or group is None or group.purchaser_id != user.id:
            raise HTTPException(status_code=403, detail="只能编辑自己创建的出游组内的条目备注")
    item.procurement_remark = (body.remark or "").strip() or None
    session.add(ProcurementEvent(cart_id=item.cart_id, actor_id=user.id, event_type="item_remark", details=(body.remark or "")[:200]))
    await session.commit()
    return cart_payload(await load_cart(session, item.cart_id))


@app.delete("/api/admin/cart-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_item(item_id: int, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> None:
    item = await session.get(CartItem, item_id, with_for_update=True)
    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found")
    session.add(ProcurementEvent(cart_id=item.cart_id, actor_id=admin.id, event_type="item_deleted", details=str(item.product_id)))
    await session.delete(item)
    await session.commit()


@app.patch("/api/admin/carts/{cart_id}/status")
async def admin_update_status(cart_id: int, body: StatusRequest, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> dict:
    cart = await load_cart(session, cart_id, for_update=True)
    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found")
    apply_status_change(cart, body.status)
    session.add(ProcurementEvent(cart_id=cart.id, actor_id=admin.id, event_type="status_changed", details=body.status.value))
    await session.commit()
    return cart_payload(await load_cart(session, cart.id))


def _protected_target(user: User, target: User, admin: User) -> None:
    """通用保护：不能操作自己，也不能操作管理员账号。"""
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="不能对自己的账号执行此操作")
    if target.role == Role.ADMIN:
        raise HTTPException(status_code=400, detail="不能对管理员账号执行此操作")


@app.get("/api/admin/users")
async def admin_list_users(_: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> list[dict]:
    users = (await session.execute(select(User).order_by(User.id))).scalars().all()
    counts = dict(
        (await session.execute(select(Cart.user_id, func.count(Cart.id)).group_by(Cart.user_id))).all()
    )
    return [user_payload(u, cart_count=counts.get(u.id, 0)) for u in users]


@app.post("/api/admin/users", status_code=status.HTTP_201_CREATED)
async def admin_create_user(body: AdminCreateUserRequest, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> dict:
    """管理员代建账号：邮箱 / 姓名 / 初始密码 / 角色 / 价格组。"""
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="A valid email address is required")
    if body.role == Role.ADMIN:
        raise HTTPException(status_code=400, detail="不能通过此接口创建 admin 角色")
    if (await session.execute(select(User).where(User.email == email))).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="该邮箱已被注册")
    if body.price_group_id is not None:
        group = await session.get(PriceGroup, body.price_group_id)
        if not group:
            raise HTTPException(status_code=404, detail="价格组不存在")
    user = User(
        email=email,
        full_name=body.full_name.strip(),
        password_hash=hash_password(body.password),
        role=body.role,
        price_group_id=body.price_group_id,
    )
    session.add(user)
    await session.commit()
    return user_payload(user)


@app.patch("/api/admin/users/{user_id}/role")
async def admin_set_role(user_id: int, body: RoleRequest, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> dict:
    """调整角色：仅允许在 user / purchaser 之间切换（不用于改动 admin 自身或他人 admin 权限）。"""
    if body.role == Role.ADMIN:
        raise HTTPException(status_code=400, detail="请勿通过此接口设置 admin 角色")
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能修改自己的角色")
    user.role = body.role
    await session.commit()
    return user_payload(user)


@app.patch("/api/admin/users/{user_id}/price-group")
async def admin_set_user_group(user_id: int, body: PriceGroupMembershipRequest, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> dict:
    """设置用户的归属价格组（null = 默认组）。"""
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能修改自己的归属组")
    if body.price_group_id is not None:
        group = await session.get(PriceGroup, body.price_group_id)
        if not group:
            raise HTTPException(status_code=404, detail="价格组不存在")
    user.price_group_id = body.price_group_id
    await session.commit()
    return user_payload(user)


@app.patch("/api/admin/users/{user_id}/active")
async def admin_set_user_active(user_id: int, body: ActiveRequest, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> dict:
    """启用 / 停用账号（停用后不可登录，数据保留可随时恢复）。"""
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    _protected_target(user, user, admin)
    user.active = body.active
    await session.commit()
    return user_payload(user)


@app.patch("/api/admin/users/{user_id}/password")
async def admin_reset_password(user_id: int, body: AdminPasswordRequest, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> dict:
    """管理员重置任意用户密码（忘记密码时使用）。"""
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.password_hash = hash_password(body.password)
    await session.commit()
    return {"ok": True, "id": user.id}


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: int, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> dict:
    """彻底删除用户：连同其账号全部清单（条目/事件）一起物理删除。

    涉及关联的处理：
    - 该用户的清单 Cart（ORM cascade 级联删除其 CartItem 与 ProcurementEvent）；
    - 清单若有归组引用，先解除 group_id（避免孤儿）；
    - 作为采购员拥有的出游组：保留数据，采购员转由当前操作的管理员代管（管理员本就具有代管任意组的权限）；
    - 作为成员加入的组：group_members 表是 ON DELETE CASCADE，删用户自动清；
    - 作为 actor 的 ProcurementEvent：外键可空，置 NULL；
    - 价格组归属 price_group_id：置 NULL。
    保护：不能删自己、不能删管理员、不能删「名下有未完成组且无其它可代管人」的采购员（此处直接转当前管理员，故可删）。
    """
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")
    if user.role == Role.ADMIN:
        raise HTTPException(status_code=400, detail="不能删除管理员账号")
    # 1) 解除该用户清单的归组引用（有组的清单先失去组，避免删除组/用户后孤儿）。
    await session.execute(update(Cart).where(Cart.user_id == user_id).values(group_id=None))
    # 2) 删除该用户所有清单（先子表后主表；bulk delete 不触发 ORM cascade，须按顺序手动删）。
    cart_ids = (await session.execute(select(Cart.id).where(Cart.user_id == user_id))).scalars().all()
    if cart_ids:
        await session.execute(delete(ProcurementEvent).where(ProcurementEvent.cart_id.in_(cart_ids)))
        await session.execute(delete(CartItem).where(CartItem.cart_id.in_(cart_ids)))
        await session.execute(delete(Cart).where(Cart.id.in_(cart_ids)))
    # 3) 该用户作为 actor 的历史事件：外键可空，置 NULL 保留事件记录。
    await session.execute(update(ProcurementEvent).where(ProcurementEvent.actor_id == user_id).values(actor_id=None))
    # 4) 作为采购员拥有的出游组：转由当前管理员代管（保留组与成员数据）。
    await session.execute(update(ProcurementGroup).where(ProcurementGroup.purchaser_id == user_id).values(purchaser_id=admin.id))
    # 5) 价格组归属置空（非强制约束）。
    if user.price_group_id is not None:
        await session.execute(update(User).where(User.id == user_id).values(price_group_id=None))
    # 6) 删除用户自身（group_members 关联由 ON DELETE CASCADE 自动清理）。
    await session.execute(delete(User).where(User.id == user_id))
    await session.commit()
    return {"action": "deleted", "id": user_id, "message": "用户及其全部清单已彻底删除"}


def _price_group_payload(group: PriceGroup, user_count: int = 0) -> dict:
    return {
        "id": group.id,
        "name": group.name,
        "tax_rate": group.tax_rate,
        "exchange_rate_jpy_cny": group.exchange_rate_jpy_cny,
        "is_default": group.is_default,
        "user_count": user_count,
    }


@app.get("/api/settings/price-groups")
async def list_price_groups(_: User = Depends(price_manager_user), session: AsyncSession = Depends(get_session)) -> list[dict]:
    groups = (await session.execute(select(PriceGroup).order_by(PriceGroup.id))).scalars().all()
    counts = dict((await session.execute(select(User.price_group_id, func.count(User.id)).where(User.price_group_id.is_not(None)).group_by(User.price_group_id))).all())
    return [_price_group_payload(g, counts.get(g.id, 0)) for g in groups]


@app.get("/api/settings/my-price-group")
async def my_price_group(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """当前登录用户「生效中」的价格分组（只读展示用）。

    有归属则返回归属组；无归属则回退默认组。普通用户也可调用，用于清单页展示税率/汇率。
    """
    group = await session.get(PriceGroup, user.price_group_id) if user.price_group_id is not None else None
    assigned = group is not None
    if group is None:
        group = (await session.execute(select(PriceGroup).where(PriceGroup.is_default.is_(True)))).scalar_one_or_none()
    if group is None:
        return {
            "id": None,
            "name": "默认组",
            "tax_rate": _FALLBACK_PARAMS["tax_rate"],
            "exchange_rate_jpy_cny": _FALLBACK_PARAMS["exchange_rate_jpy_cny"],
            "is_default": True,
            "assigned": False,
            "user_count": 0,
        }
    return {**_price_group_payload(group), "assigned": assigned}


@app.post("/api/settings/price-groups", status_code=status.HTTP_201_CREATED)
async def create_price_group(body: PriceGroupRequest, _: User = Depends(price_manager_user), session: AsyncSession = Depends(get_session)) -> dict:
    name = body.name.strip()
    if (await session.execute(select(PriceGroup).where(PriceGroup.name == name))).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="已存在同名价格组")
    group = PriceGroup(name=name, tax_rate=body.tax_rate, exchange_rate_jpy_cny=body.exchange_rate_jpy_cny, is_default=False)
    session.add(group)
    await session.commit()
    await refresh_runtime_settings()
    return _price_group_payload(group)


@app.put("/api/settings/price-groups/{group_id}")
async def update_price_group(group_id: int, body: PriceGroupRequest, _: User = Depends(price_manager_user), session: AsyncSession = Depends(get_session)) -> dict:
    group = await session.get(PriceGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="价格组不存在")
    name = body.name.strip()
    if name != group.name:
        existing = (await session.execute(select(PriceGroup).where(PriceGroup.name == name))).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="已存在同名价格组")
    group.name = name
    group.tax_rate = body.tax_rate
    group.exchange_rate_jpy_cny = body.exchange_rate_jpy_cny
    await session.commit()
    await refresh_runtime_settings()
    return _price_group_payload(group)


@app.delete("/api/settings/price-groups/{group_id}")
async def delete_price_group(group_id: int, _: User = Depends(price_manager_user), session: AsyncSession = Depends(get_session)) -> dict:
    group = await session.get(PriceGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="价格组不存在")
    if group.is_default:
        raise HTTPException(status_code=400, detail="默认组不可删除")
    user_count = (await session.execute(select(func.count(User.id)).where(User.price_group_id == group_id))).scalar_one()
    if user_count:
        raise HTTPException(status_code=400, detail=f"仍有 {user_count} 个用户归属该组，请先调整其归属")
    await session.delete(group)
    await session.commit()
    await refresh_runtime_settings()
    return {"ok": True, "id": group_id}


@app.get("/api/settings/registration")
async def get_registration_setting() -> dict:
    """注册开关（公开可读，登录页据此决定是否展示注册入口）。"""
    return {"allow_registration": REGISTRATION_OPEN}


@app.put("/api/settings/registration")
async def update_registration_setting(body: RegistrationRequest, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> dict:
    global REGISTRATION_OPEN
    row = await session.get(Setting, "allow_registration")
    if row:
        row.value = "1" if body.allow_registration else "0"
    else:
        session.add(Setting(key="allow_registration", value="1" if body.allow_registration else "0"))
    await session.commit()
    REGISTRATION_OPEN = body.allow_registration
    return {"allow_registration": REGISTRATION_OPEN}


# ============ 出游采购组 ============

# 每个采购员累计最多创建的出游组数（含已结束历史组）。
MAX_GROUPS_PER_PURCHASER = 3


async def _require_group_creator(session: AsyncSession, user: User) -> None:
    """管理员拥有最高权限，与采购员一样可以创建出游采购组。"""
    if user.role not in (Role.ADMIN, Role.PURCHASER):
        raise HTTPException(status_code=403, detail="只有管理员或采购员可以创建出游采购组")


def _rand_invite_code() -> str:
    """4 位数字邀请码（随机，碰撞由调用方重试）。"""
    return f"{random.randint(0, 9999):04d}"


@app.post("/api/groups", status_code=status.HTTP_201_CREATED)
async def create_group(body: GroupCreateRequest, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """管理员 / 采购员创建出游采购组（标题 + 出游日期区间）。

    配额：采购员累计最多 MAX_GROUPS_PER_PURCHASER 个组（含历史组）；管理员不受配额限制。
    返回 4 位邀请码：需求人凭码自助加入，或由创建者批量拉入。
    """
    await _require_group_creator(session, user)
    if body.end_date < body.start_date:
        raise HTTPException(status_code=422, detail="结束日期不能早于开始日期")
    if user.role == Role.PURCHASER:
        created = (await session.execute(select(func.count(ProcurementGroup.id)).where(ProcurementGroup.purchaser_id == user.id))).scalar_one()
        if created >= MAX_GROUPS_PER_PURCHASER:
            raise HTTPException(status_code=400, detail=f"每个采购员累计最多创建 {MAX_GROUPS_PER_PURCHASER} 个出游组，已达上限")
    for _ in range(50):
        code = _rand_invite_code()
        exists = (await session.execute(select(ProcurementGroup.id).where(ProcurementGroup.invite_code == code).limit(1))).scalars().first()
        if not exists:
            break
    else:  # pragma: no cover - 4 位码空间足够大，几乎不可能 50 次全撞
        raise HTTPException(status_code=500, detail="邀请码生成失败，请重试")
    group = ProcurementGroup(
        title=body.title.strip(),
        purchaser_id=user.id,
        invite_code=code,
        start_date=body.start_date,
        end_date=body.end_date,
        status=GroupStatus.OPEN,
    )
    session.add(group)
    await session.commit()
    group_id = group.id
    return group_detail_payload(await load_group(session, group_id, detail=True))


@app.get("/api/groups")
async def list_groups(_: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> list[dict]:
    """管理员查看全部出游组（只读视图：基础信息 + 成员 + 条目汇总）。"""
    groups = (await session.execute(_group_detail_select().order_by(ProcurementGroup.id.desc()))).scalars().all()
    return [group_detail_payload(g) for g in groups]


@app.get("/api/groups/me")
async def my_groups(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> list[dict]:
    """当前用户视角的出游组：
    - 采购员 / 管理员：自己创建的全部组（含组内条目，工作台勾选用）；
      管理员额外包含自己以成员身份加入的组（管理员拥有最高权限）。
    - 普通用户：自己作为成员加入的进行中组（提交清单时选择归属）。
    """
    if user.role in (Role.PURCHASER, Role.ADMIN):
        owned = (
            await session.execute(
                _group_detail_select().where(ProcurementGroup.purchaser_id == user.id).order_by(ProcurementGroup.id.desc())
            )
        ).scalars().all()
        rows = [group_detail_payload(g) for g in owned]
        if user.role == Role.ADMIN:
            seen = {g.id for g in owned}
            joined = (
                await session.execute(
                    _group_detail_select()
                    .join(group_members, group_members.c.group_id == ProcurementGroup.id)
                    .where(group_members.c.user_id == user.id)
                    .order_by(ProcurementGroup.id.desc())
                )
            ).scalars().all()
            rows += [group_detail_payload(g) for g in joined if g.id not in seen]
        return rows
    statement = (
        _group_select()
        .join(group_members, group_members.c.group_id == ProcurementGroup.id)
        .where(group_members.c.user_id == user.id)
        .order_by(ProcurementGroup.id.desc())
    )
    return [group_payload(g) for g in (await session.execute(statement)).scalars().all()]


@app.get("/api/groups/member-options")
async def group_member_options(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> list[dict]:
    """采购员 / 管理员拉人入组时的候选用户：全部普通用户（user，启用中）。

    需求人自助加入靠邀请码；此处只服务「采购员批量拉人」的场景。
    """
    if user.role not in (Role.PURCHASER, Role.ADMIN):
        raise HTTPException(status_code=403, detail="无权限查看用户列表")
    users = (
        await session.execute(
            select(User).where(User.role == Role.USER, User.active.is_(True)).order_by(User.id)
        )
    ).scalars().all()
    return [member_payload(u) for u in users]


@app.post("/api/groups/{group_id}/members", status_code=status.HTTP_201_CREATED)
async def add_group_members(group_id: int, body: GroupMembersRequest, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """采购员（组创建者）批量把需求人拉进自己的出游组；管理员可代操作任意组。"""
    group = await load_group(session, group_id, for_update=True)
    if not group:
        raise HTTPException(status_code=404, detail="出游组不存在")
    if user.role != Role.ADMIN and group.purchaser_id != user.id:
        raise HTTPException(status_code=403, detail="只能管理自己创建的出游组")
    if group.status == GroupStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="组已完成，不能新增成员")
    ids = list(dict.fromkeys(body.user_ids))
    users = (await session.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    if len(users) != len(ids):
        raise HTTPException(status_code=404, detail="部分用户不存在")
    for target in users:
        if target.role == Role.ADMIN:
            raise HTTPException(status_code=400, detail=f"不能把管理员「{target.full_name}」拉入采购组")
        if target.id == group.purchaser_id:
            continue  # 采购员默认即可处理组内条目，无需把自己加入成员表
        if target not in group.members:
            group.members.append(target)
    await session.commit()
    return group_payload(await load_group(session, group_id))


@app.post("/api/groups/join", status_code=status.HTTP_201_CREATED)
async def join_group(body: GroupJoinRequest, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """需求人凭 4 位邀请码自助加入出游采购组（可同时加入多个组）。"""
    group = (
        await session.execute(
            select(ProcurementGroup).options(selectinload(ProcurementGroup.members)).where(ProcurementGroup.invite_code == body.invite_code.strip())
        )
    ).scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="邀请码无效，未找到对应出游组")
    if group.status == GroupStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="该出游组已结束，无法加入")
    if user.id == group.purchaser_id:
        raise HTTPException(status_code=400, detail="这是你自己创建的出游组")
    if user in group.members:
        raise HTTPException(status_code=409, detail="你已在当前出游组中")
    group.members.append(user)
    await session.commit()
    group_id = group.id
    return group_payload(await load_group(session, group_id))


@app.patch("/api/groups/{group_id}")
async def update_group(group_id: int, body: GroupUpdateRequest, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """修改组标题/日期，或标记完成（采购员自己；管理员可代操作任意组）。"""
    group = await load_group(session, group_id, for_update=True)
    if not group:
        raise HTTPException(status_code=404, detail="出游组不存在")
    if user.role != Role.ADMIN and group.purchaser_id != user.id:
        raise HTTPException(status_code=403, detail="只能管理自己创建的出游组")
    updates = body.model_dump(exclude_unset=True)
    if "title" in updates and updates["title"] is not None:
        group.title = updates["title"].strip()
    if "start_date" in updates and updates["start_date"] is not None:
        group.start_date = updates["start_date"]
    if "end_date" in updates and updates["end_date"] is not None:
        group.end_date = updates["end_date"]
    if group.end_date < group.start_date:
        raise HTTPException(status_code=422, detail="结束日期不能早于开始日期")
    if "status" in updates and updates["status"] is not None:
        if updates["status"] == GroupStatus.OPEN and group.status == GroupStatus.COMPLETED:
            raise HTTPException(status_code=400, detail="已完成的出游组不能重新打开")
        group.status = updates["status"]
        group.completed_at = datetime.now(timezone.utc) if updates["status"] == GroupStatus.COMPLETED else None
    await session.commit()
    return group_detail_payload(await load_group(session, group_id, detail=True))


@app.delete("/api/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> None:
    """删除出游组：仅允许没有已归组清单（Cart.group_id 未引用）时删除，否则提示改用「完成」。"""
    group = await load_group(session, group_id, for_update=True)
    if not group:
        raise HTTPException(status_code=404, detail="出游组不存在")
    if user.role != Role.ADMIN and group.purchaser_id != user.id:
        raise HTTPException(status_code=403, detail="只能管理自己创建的出游组")
    referenced = (await session.execute(select(Cart.id).where(Cart.group_id == group_id).limit(1))).scalars().first()
    if referenced:
        raise HTTPException(status_code=409, detail="组内已有归组清单，不能删除；可将组标记为完成")
    await session.delete(group)
    await session.commit()

