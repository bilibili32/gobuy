# 买办采购系统 — 项目交接说明

面向 AI 编程工具（Codex / Trae / Cursor 等）的项目上下文。继续开发前请先读完本文件。

## 1. 项目概述

内部集中采购系统，品牌名「买办」。普通用户维护个人采购清单，采购员通过「出游采购组」组织收单，管理员统一推进采购状态。

- 版本：`v0.2`（详见 `VERSION` 和 `CHANGELOG.md`）
- 本目录是**开发主目录**：含真实 `.env` 和本地数据库，可直接运行和冒烟测试
- 公开脱敏副本另存于 `../procurement-app-github-20260906/`，仅用于 GitHub 发布
- 本目录**不是 git 仓库**；如需版本管理请先 `git init`，`.gitignore` 已忽略 `.env`

## 2. 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | FastAPI（async）+ SQLAlchemy 2.0 async + Alembic |
| 数据库 | PostgreSQL 16（容器 `postgres:16-alpine`） |
| 缓存 | Redis 7 |
| 前端 | 原生静态 HTML / CSS / JavaScript，由 nginx 提供 |
| 编排 | Docker Compose |

## 3. 本地启动

```bash
docker compose up -d --build
```

访问地址：

- 用户首页：<http://localhost:8080/>
- 管理台：<http://localhost:8080/admin.html>
- 采购员：<http://localhost:8080/purchaser.html>
- 成员清单：<http://localhost:8080/member.html>
- API 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/health>

管理员账号：邮箱见 `.env` 的 `BOOTSTRAP_ADMIN_EMAIL`，密码见同文件的 `BOOTSTRAP_ADMIN_PASSWORD`。**不要把密码写进任何文档、代码或提交记录。**

### 关键：改代码后必须重新构建

后端和前端代码都烘焙进镜像，**`restart` 不会加载新代码**，必须：

```bash
docker compose up -d --build
```

### 前端新增文件要注意

`frontend.Dockerfile` 是逐文件 `COPY`，新增页面或 CSS 必须在 Dockerfile 里补一行 `COPY`，否则镜像里没有该文件。

## 4. 冒烟测试

```bash
bash scripts/smoke_test.sh
```

当前基线：**277 项通过，0 项失败**。

冒烟脚本会自动从 `.env` 读取管理员密码。长期约束：

- 商品数量 ≤ 20
- 用户数量 ≤ 10
- 测试账号用时间戳 `STAMP` 生成，避免冲突

冒烟失败时先区分两种情况：**产品 bug** 还是**断言过期**（业务语义变更后脚本未同步），不要直接改断言掩盖问题。

## 5. 业务规则

### 角色

- `admin`：管理员，可管理用户、商品、价格分组、所有清单
- `purchaser`：采购员，可创建出游采购组（累计最多 3 个）、管理组内清单
- `user`：普通用户，维护个人清单、通过邀请码加入采购组

### 清单状态流转

```text
draft → submitted → locked → success / failed
```

出游组场景：`start_date` 到达**前**提交 → `submitted`（可撤回）；到达**当天起**提交即封板 → 直接 `locked`（冻结单价），并自动为需求人开立下一批空草稿（`carts.batch_no` 同组内递增：0 = 未提交草稿，≥1 = 批次号）。封板批不可自行撤回（409），只能由该组采购员或管理员经 `PATCH /api/groups/{id}/carts/{cart_id}/status` 解锁（`locked->draft`）后修改重提。

### 价格算法（重要）

统一口径：**录入的原价 = 税前原价**。

```text
税前价 = 原价
含税价 = 原价 × (1 + 价格组税率)
人民币价 = 含税价 × 日元汇率（JPY 商品）
```

- 后端计算函数：`backend/app/main.py` 的 `effective_price`
- 商品/清单序列化统一输出 `pretax_price_cents`、`taxed_price_cents`、`price_cny_cents`
- 旧字段 `tax_included` 仅为兼容保留，**不改变计算结果**，前端已移除该切换 UI
- 用户侧三个价格框均为只读，任何角色不可修改

### 价格分组

`PriceGroup` 含税率、JPY→CNY 汇率、默认标识。管理员和采购员可增删改；普通用户只能通过 `/api/settings/my-price-group` 查看当前组。

### 出游采购组

采购员创建，成员用邀请码加入，整单提交归组。管理员可创建、查看、代管、改组、完成、删除、拉人。组含 `start_date/end_date`：`end_date` 过后停止收单，`start_date` 到达后转为按批次收单（见「清单状态流转」），组详情 `batches` 聚合每人每批（`batch_no/cart_id/status`）。

### 商品来源

支持 kakaku.com 与 kitamuracamera.jp 的公开商品解析。价格含币种和税前/税后标识，商品支持图片、类型、备注和多颜色变体。

## 6. 前端结构

五个页面，共享 `auth.js` 和 `responsive.css`：

| 文件 | 用途 |
| --- | --- |
| `login.html` | 登录 / 注册 |
| `index.html` | 用户首页：个人清单 + 批次条（锁定只读 / 草稿可编辑，提交后切下一批） |
| `admin.html` | 管理台，四个标签页 |
| `purchaser.html` | 采购员工作台 |
| `member.html` | 成员清单页 |
| `auth.js` | 共享鉴权、请求封装、图片灯箱 |
| `responsive.css` | 全局响应式与可访问性样式 |

## 7. 云部署

当前服务器实际方案：**腾讯云 Ubuntu + 宝塔面板 + Nginx 反向代理**。

- 前端容器绑定 `127.0.0.1:8080:80`，由宝塔 Nginx 反代
- **服务器上已移除 Caddy**，不要直接用仓库里带 Caddy 的 `docker-compose.cloud.yml`，会与宝塔抢 80/443
- 更新服务器：`docker compose -f docker-compose.cloud.yml --env-file .env.cloud up -d --build`
- **严禁 `down -v`**，会删除数据库卷

服务器配置细节、域名和路径等敏感信息记录在 `CHANGELOG.md` 中，不要复制到公开仓库。

## 8. 重要工程经验

异步 ORM：

- 列表/详情查询用 `selectinload` 预加载关系
- 同会话关系陈旧时用 `populate_existing=True`
- 不要在 async `expire_on_commit=False` 下依赖 `expire_all()`
- 直接写 FK（如 `cart.group_id = x`）不会同步已加载的关系属性（`cart.group` 仍为旧值/None）；后续逻辑若依赖该关系需一并赋值关系对象（`cart.group = target_group`），否则守卫/业务判断会误判

数据库：

- PostgreSQL 枚举新增值需 `ALTER TYPE ... ADD VALUE IF NOT EXISTS`
- 批量删除用户时，先删 `procurement_events`、`cart_items`，再删 `carts`

前端：

- 模态层必须挂在 `<body>` 直接子级，否则会被隐藏 tab 的 `display:none` 一并隐藏
- 响应式改动后要扫描多个视口，检查 `rect.right > innerWidth` 和容器 `scrollWidth`
- CSS 无法用 `node --check` 校验，需靠浏览器实测

## 9. 禁止操作

- 不要提交 `.env`、`.env.cloud`、`.env.production`
- 不要把真实密码、JWT 密钥、服务器域名写进代码或文档
- 不要用 `docker compose down -v`（会丢数据卷）
- 不要用 `restart` 代替 `up -d --build`
- 不要删除 `frontend.Dockerfile` 里已有的 COPY 行
- 修改业务语义后，同步更新 `scripts/smoke_test.sh` 的断言和 `CHANGELOG.md`

## 10. 改动流程建议

1. 修改代码
2. `docker compose up -d --build` 重新构建
3. 访问页面验证
4. `bash scripts/smoke_test.sh` 跑全量冒烟
5. 更新 `CHANGELOG.md`
6. 如需发布，生成不含 `.env`、日志、备份的脱敏更新包
