# 国家价格参数索引 YAML + 新建分组选国家继承

## Context

当前系统硬编码日本参数：税率 10%、汇率 0.048（1 日元 = 元）、货币 JPY/CNY，价格折算逻辑 `effective_price()` 只识别 JPY 分支，抓取器只有日本 kakaku/kitamura。用户需要新建一个 YAML 文件集中索引各国税率/货币/汇率/比价网站，新建价格分组时选择国家即可继承基础参数，且保持简洁易维护。

用户已确认：
- 比价网站解析：**只做索引 + 前端展示**（YAML 配置 scraper 字段），抓取路由维持现状不改。
- 预置国家：**日本 + 常见示例**（美国/韩国/中国香港/中国大陆等，汇率/税率填合理默认值）。

## 设计要点

- YAML 是唯一权威来源；后端启动读取并缓存，前端通过新接口拉取下拉选项。
- 汇率字段名 `exchange_rate_jpy_cny` **保留不改**（避免数据库迁移破坏），语义泛化为「1 本币 = x 元人民币」；`effective_price()` 折算分支从「只认 JPY」泛化为「非 CNY 一律按汇率折算」，对现有 JPY 数据行为完全一致。
- 货币符号由前端 `money()` 内置映射展示（与 YAML 同步维护），避免异步时序问题。
- 分组保存时持久化 `country`，分组列表展示国家徽标；**只在新建时选择国家**，行内不提供改国家（保持简单）。

## 新增文件

1. `backend/app/countries.yml` — 国家索引（每条：code / name / currency / symbol / tax_rate / exchange_rate_cny / scrapers 列表）：

```yaml
countries:
  - code: jp
    name: 日本
    currency: JPY
    symbol: "¥"
    tax_rate: 10.0
    exchange_rate_cny: 0.048
    scrapers: [kakaku, kitamura]
  - code: us
    name: 美国
    currency: USD
    symbol: "$"
    tax_rate: 8.0
    exchange_rate_cny: 7.20
    scrapers: [amazon]
  - code: kr
    name: 韩国
    currency: KRW
    symbol: "₩"
    tax_rate: 10.0
    exchange_rate_cny: 0.0052
    scrapers: []
  - code: hk
    name: 中国香港
    currency: HKD
    symbol: "HK$"
    tax_rate: 0.0
    exchange_rate_cny: 0.92
    scrapers: []
  - code: cn
    name: 中国大陆
    currency: CNY
    symbol: "¥"
    tax_rate: 13.0
    exchange_rate_cny: 1.0
    scrapers: []
```

2. Alembic 迁移 `backend/migrations/versions/0009_price_group_country.py`（链 0008 → 0009）：`price_groups` 加 `country VARCHAR(8) NULL`。

## 后端改动

- `backend/app/models.py`：`PriceGroup` 加 `country: Mapped[str | None] = mapped_column(String(8), nullable=True)`（L53-63 区域）。
- `backend/requirements.txt`：加 `PyYAML`。
- `backend/app/main.py`：
  - 顶部常量 `COUNTRIES_FILE`（指向 `countries.yml`）+ 全局 `COUNTRIES: list[dict]`；新增 `load_countries()`（yaml.safe_load，字段校验兜底），在 lifespan 启动（`seed_data`/`refresh_runtime_settings` 附近）调用一次。
  - 新接口 `GET /api/settings/countries`（`price_manager_user` 依赖，与价格组接口一致），返回 `[{code,name,currency,symbol,tax_rate,exchange_rate_cny,scrapers}]`，供 admin/purchaser 下拉。
  - `PriceGroupRequest`（L200-204）加可选 `country: str | None = Field(default=None, max_length=8)`。
  - `_price_group_payload()`（L1535-1543）返回 `country`；`create_price_group()`（L1576）与 `update_price_group()`（L1588）保存/更新 `group.country`（更新时传空则保留原值）。
  - `seed_data()` 默认组（L729）设置 `country="jp"`。
  - `effective_price()`（L256-275）：把 `if currency == "JPY"` 分支改为 `if currency != "CNY"`，折算公式不变（`cny = round(taxed * p["exchange_rate_jpy_cny"] * 100)`）；CNY 仍 `cny = taxed`。注释同步说明字段语义为本币→CNY。
  - `my_price_group()`（L1553）payload 追加 `currency` / `currency_symbol`（按 group.country 从 COUNTRIES 查；无 country 回退 JPY），供用户页展示「1 本币 = ¥x」。

## 前端改动

- `frontend/auth.js`：
  - `money()`（L75-78）泛化：内置 `CURRENCY_SYMBOL = {CNY:"¥", JPY:"¥", USD:"$", KRW:"₩", HKD:"HK$", EUR:"€", GBP:"£"}`；JPY 保持「¥ n 円」格式，CNY 保持分/100，其他本币按整数显示符号 + 数值。
- `frontend/admin.html`：
  - 新建分组表单（L260-265 `ng-*`）加「国家」`<select id="ng-country">`；页面加载时 `fetch("/api/settings/countries")` 填充选项（首项为占位「选择国家」）；`onchange` 自动填充 `ng-tax` / `ng-rate` 并更新汇率 label 文案（`1 {货币} = 元`）与比价网站提示。
  - `addGroup()`（L655-665）读取 `ng-country` 一并提交。
  - `renderPriceGroups()`（L641-654）组行组名后加国家徽标（如「日本」），无 country 不显示。
  - 汇率 label 文案泛化为「汇率（1 本币 = 元）」（L263、L649）。
- `frontend/purchaser.html`：同样处理 `pgn-*` 表单（L115-120 加国家下拉 + onchange 填充 L117-118），`addPriceGroup()`（L168）提交 country，分组列表（L155-165 `pgt-*` 行）显示国家徽标，label 文案泛化（L118、L161）。
- `frontend/index.html`：用户页只读展示（L251）从 `my-price-group` 的 `currency`/`currency_symbol` 字段渲染「{符号}汇率 1 {currency} = ¥{rate}」，无 country 时保持「日元」。

## 同步与部署（沿用既有流程）

- 逐文件 `cp` 同步 `procurement-app` → `MAIBAN`，覆盖清单：
  - `backend/app/countries.yml`（新增）
  - `backend/app/main.py`、`backend/app/models.py`、`backend/requirements.txt`
  - `backend/migrations/versions/0009_price_group_country.py`（新增）
  - `frontend/admin.html`、`frontend/purchaser.html`、`frontend/auth.js`、`frontend/index.html`
- 不覆盖 `.env*`、`docker-compose.cloud.yml`、`DEPLOY-CLOUD.md`、`deploy/backup.sh`。
- 部署：backend rebuild + alembic upgrade head（执行 0009）+ frontend rebuild（`docker compose up -d --build backend frontend`）。

## 验证

1. 后端启动无报错，`/api/settings/countries` 返回 5 个国家。
2. admin / purchaser 新建分组：选「美国」自动填充税率 8 / 汇率 7.2，label 变「1 USD = 元」，提示比价网站 amazon；保存后分组列表显示「美国」徽标。
3. 选「日本」填充 10 / 0.048，与原默认一致。
4. 现有 JPY 商品价格展示不变（税前/含税/人民币数字与改造前一致）；`my-price-group` 接口仍返回可用字段。
5. 用户页只读汇率行按分组国家展示货币符号。
6. 迁移 0009 可正常 upgrade / downgrade。
