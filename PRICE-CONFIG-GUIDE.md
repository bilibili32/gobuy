# 文件结构与「税率 / 货币类型」修改指南

> 本文档面向需要调整价格计算参数（税率、汇率、货币币种）的维护者。
> 系统当前按 **日元（JPY）采购 → 人民币（CNY）结算** 设计：商品原价按日元录入，含税价 = 原价 × (1 + 税率)，人民币价 = 含税价 × 日元汇率。

---

## 一、项目文件结构

```
procurement-app/
├── backend/                          # FastAPI 后端
│   ├── app/
│   │   ├── main.py                   # 全部业务接口 + 价格计算核心（effective_price）
│   │   ├── models.py                 # SQLAlchemy 模型（PriceGroup / Product / Cart）
│   │   ├── db.py                     # 数据库会话
│   │   ├── security.py               # 密码 / Token
│   │   ├── worker.py                 # 后台同步（商品抓取入库）
│   │   ├── kakaku.py                 # 价格抓取器（価格.com，价格标 JPY）
│   │   └── kitamura.py               # 价格抓取器（KITAMURA，价格标 JPY）
│   ├── migrations/versions/          # Alembic 迁移（0001 ~ 0008）
│   ├── Dockerfile / entrypoint.sh
│   └── requirements.txt
├── frontend/                         # 静态前端（Nginx 托管）
│   ├── login.html                    # 登录页
│   ├── index.html                    # 普通用户「我的清单」
│   ├── member.html                   # 成员清单（按组查看）
│   ├── purchaser.html                # 采购员工作台（可维护税率/汇率）
│   ├── admin.html                    # 管理台（可维护税率/汇率）
│   ├── auth.js                       # 通用 API + 金额格式化 money()
│   ├── export.js                     # 对账单导出
│   └── responsive.css                # 共享样式
├── scripts/smoke_test.sh             # 冒烟测试
├── docker-compose.yml                # 本地开发
├── docker-compose.cloud.yml          # 云服务器生产部署
└── MAIBAN/                           # 云部署副本（改动后需逐文件同步）
```

---

## 二、修改「税率」

税率属于 **价格算法分组（PriceGroup）**，每组一套。默认税率 **10%**。

### 2.1 数据库模型

| 文件 | 位置 | 说明 |
|---|---|---|
| `backend/app/models.py` | `PriceGroup.tax_rate`（L60） | 价格分组表存储税率字段（Float） |

> 已上线数据库如需改字段类型，需新增 Alembic 迁移（`migrations/versions/0009_*.py`）。

### 2.2 计算核心（后端，最关键的修改点）

| 文件 | 位置 | 说明 |
|---|---|---|
| `backend/app/main.py` | `effective_price()` L270 | `taxed = round(price_cents * (1 + tax_rate / 100.0))` —— **含税价在此计算** |
| `backend/app/main.py` | `_FALLBACK_PARAMS` L222 | 内置兜底参数 `{"tax_rate": 10.0, "exchange_rate_jpy_cny": 0.048}`，无价格组时使用 |
| `backend/app/main.py` | `refresh_runtime_settings()` L224-235 | 启动/重载时把数据库价格组读入内存缓存 `PRICE_GROUPS` |
| `backend/app/main.py` | 建库 seed L729 | 初始化「默认组」时写入 `tax_rate=10.0` |

### 2.3 接口校验（后端）

| 文件 | 位置 | 说明 |
|---|---|---|
| `backend/app/main.py` | L155-156、L202-203 | `PriceGroupCreate / PriceGroupUpdate` Pydantic 模型，`tax_rate: float(ge=0, le=100)`，超界会报错 |

### 2.4 前端输入框（直接改这里即可让管理员/采购员调整）

| 文件 | 位置 | 说明 |
|---|---|---|
| `frontend/admin.html` | L200（`set-tax`）、L262（`ng-tax`）、L648（`pg-tax-{id}`） | 管理台默认税率 / 新增分组 / 分组列表的税率输入 |
| `frontend/purchaser.html` | L117（`pgn-tax`）、L160（`pgt-tax-{id}`） | 采购员新增分组 / 分组列表的税率输入 |
| `frontend/index.html` | L251 | 用户端只读展示「税率 x%」 |

> 输入框默认 `value="10"`、`min=0 max=100 step=0.1`，如需支持更高税率记得同步改 `max`。

### 2.5 修改方式建议

- **改某分组税率**：后台 → 价格算法分组 → 编辑该组税率 → 保存（走 `PUT /api/settings/price-groups/{id}`，后端写库并重载缓存）。
- **改全局默认**：价格组里编辑「默认组」，或改 `_FALLBACK_PARAMS` 兜底值。
- **改系统默认初始值**：`main.py` L729 seed + 各前端输入框默认 `value`。

---

## 三、修改「货币类型 / 汇率」

系统目前只区分 **JPY（日元，整数円）** 与 **CNY（人民币，分）** 两种币种。汇率字段 `exchange_rate_jpy_cny` 表示 **1 日元 = x 元人民币**，默认 **0.048**。

### 3.1 数据库模型

| 文件 | 位置 | 说明 |
|---|---|---|
| `backend/app/models.py` | `PriceGroup.exchange_rate_jpy_cny`（L61） | 每组的日元→人民币汇率 |
| `backend/app/models.py` | `Product.currency`（L102） | 商品币种（默认 `CNY`，抓取商品为 `JPY`） |
| `backend/app/models.py` | L100 注释 | `price_cents` = 币种最小单位：CNY 为「分」，JPY 为「円」 |

### 3.2 折算逻辑（后端，最关键的修改点）

| 文件 | 位置 | 说明 |
|---|---|---|
| `backend/app/main.py` | `effective_price()` L271-274 | **货币分支**：`currency == "JPY"` 时 `cny = taxed × 汇率 × 100`；否则 `cny = taxed`（视为已人民币） |
| `backend/app/main.py` | `_FALLBACK_PARAMS` L222 | 兜底汇率 0.048 |
| `backend/app/main.py` | 建库 seed L729 | 默认组初始汇率 0.048 |

> **如果新增第三种货币**（如 USD），需要：
> 1. `effective_price()` 增加 `currency == "USD"` 分支及对应汇率字段；
> 2. `PriceGroup` 表增加 `exchange_rate_*_cny` 字段 + Alembic 迁移；
> 3. `models.py` / `main.py` 所有 Pydantic 与 payload 同步加字段；
> 4. 前端 `money()` 及各页「人民币」展示逻辑同步。

### 3.3 商品币种来源（哪些地方写死 JPY）

| 文件 | 位置 | 说明 |
|---|---|---|
| `backend/app/kakaku.py` | L189、L210 | 価格.com 抓取，`currency="JPY"` |
| `backend/app/kitamura.py` | L118 | KITAMURA 抓取，`currency="JPY"` |
| `backend/app/worker.py` | L64 | 后台同步入库，`currency="JPY"` |
| `backend/app/main.py` | L1007、L1029、L1055 | 手工加商品（解析结果 / 手动录入）默认 JPY |

### 3.4 前端金额格式化与展示

| 文件 | 位置 | 说明 |
|---|---|---|
| `frontend/auth.js` | `money()` L75-78 | **币种格式化核心**：`JPY → "¥ n 円"`，其余 `→ "¥ 分/100"`；改币种符号/精度在此 |
| `frontend/auth.js` | `priceStack()` L96-97 | 税前 / 含税 / 人民币三行展示 |
| `frontend/auth.js` | `cnyTotal()` L101 | 人民币合计 |
| `frontend/index.html` | L161-162、L698-699、L747 | 用户端合计 + 三价展示 + 分组小计「≈ 人民币」 |
| `frontend/purchaser.html` | L327、L353-357 | 采购员端三价 / 小计 |
| `frontend/admin.html` | L817、L826、L835-839、L890-892 | 管理台条目 / 商品库 / 清单合计 |
| `frontend/member.html` | L112-115、L128、L148-153、L198-203 | 成员清单三价 / 统计 |
| `frontend/export.js` | L138-141、L236-244、L290-303 | 对账单导出的币种与人民币折算 |

> 前端所有「人民币」展示都来自后端返回的 `price_cny_cents` 字段，后端不改、前端展示数字不会变。

### 3.5 汇率修改方式建议

- **日常调汇率**：管理台 / 采购员 → 价格分组 → 改「汇率（1 日元 = 元）」→ 保存。立即生效（单进程内存缓存，无需重启）。
- **改默认初始值**：`main.py` L222 `_FALLBACK_PARAMS` + L729 seed + 前端各输入框默认 `value="0.048"`。

---

## 四、修改后必须同步的部署副本

- 改的是 `procurement-app/`（开发根目录），上线前需**逐文件 `cp` 同步到 `MAIBAN/`** 对应路径。
- 前端改动 → `docker compose up -d --build frontend`（前端 bake 进镜像，不能只 restart）。
- 后端改动（如改 `effective_price` / 模型）→ rebuild backend + 执行 Alembic 迁移。
- 涉及数据库结构（新增字段/表）必须新增迁移，**不要直接改旧迁移文件**。

---

## 五、快速定位速查表

| 想改什么 | 唯一核心位置 |
|---|---|
| 含税价算法 | `main.py` → `effective_price()` L270 |
| 日元→人民币折算 | `main.py` → `effective_price()` L271-274 |
| 默认税率/汇率兜底 | `main.py` → `_FALLBACK_PARAMS` L222 |
| 默认组初始值 | `main.py` L729（seed） |
| 前端金额符号/格式 | `auth.js` → `money()` L75-78 |
| 商品币种写入 | `kakaku.py` / `kitamura.py` / `worker.py` / `main.py` 手工加商品 |
| 分组参数存储 | `models.py` → `PriceGroup`（L53-63） |
