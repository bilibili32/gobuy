# Changelog — 内部集中采购系统

版本规则：无 git 仓库，以目录快照 + 本文件记录版本演进。
节点快照存放于 `../backups/procurement-app/`（相对项目根，即 workbuddy/backups 下）。

## v0.2（开发中）

### 2026-09-08 — 用户页批次列表：锁定批只读可查看，提交后切到下一批新清单

按实测反馈补齐用户侧「批次列表 + 切换」：锁定批次仍能看见、不能编辑；管理员/采购员解锁后原条目保留并恢复可编辑；1 号清单锁定后自动生成 2 号清单并可继续加购。

后端：
- 新增 `GET /api/carts/me/batches`（我的全部批次摘要）与 `GET /api/carts/me/{cart_id}`（任意本人批次明细，锁定批只读）。`/batches` 必须声明在 `/{cart_id}` 之前，避免被路径参数吃掉。
- 加购/提交/撤回/重开请求体增加可选 `cart_id`；缺省保持旧客户端行为（最新草稿 / 最新 submitted·failed）。
- 统一 helper `editable_cart_for`：指定 cart_id 必须是本人且 `draft`，否则 404/409。

前端（`index.html`）：
- 「我的清单」增加批次条：第 N 批 / 新清单 chip，锁定批可点开只读，草稿批可编辑。
- 提交若封板（`locked`）则自动切到最新草稿，可继续添加商品。
- 加购/提交/撤回/重开带当前 `cart_id`；非草稿前端拦截。

验证：冒烟 8.55.3b（列表/按 id 查看/指定锁定批加购 409）；指定新草稿加购后删除测试条目，避免占用空占位草稿破坏「解锁后当前草稿即第2批」。镜像重建后全量冒烟 **277 项通过，0 项失败**（此前基线 261）。

### 2026-09-08 — 出游组批次机制（出游开始后提交即封板，逐批收单）

出游采购组到达 `start_date` 当天起进入采购期：需求人每「提交」一次清单即锁定为一批，冻结单价，系统自动为其开立下一批空草稿继续追加；采购员/管理员可在组内按批次锁定或解锁。

数据模型与后端：
- 新增 Alembic 迁移 `0007_cart_batch_no.py`：`carts.batch_no`（INTEGER NOT NULL 默认 0）。0 = 尚未提交的草稿；提交时分配 `>=1`，同一用户同一组内每次封板递增。
- 提交语义收口：`start_date` 到达前提交 → `submitted`（可自行撤回）；到达后提交即封板 → `locked`（冻结单价，见 `apply_status_change`），并自动为下一批占位空草稿（`draft_cart` 取/建，仅限进行中且已开始的组，见 `ensure_next_draft`）。
- 已开始组内已提交/已封板批不得自行撤回/删改：`withdraw` 对组已开始且已归组批次返回 409（提示联系采购员或管理员解锁）。
- 新增组内批次状态端点 `PATCH /api/groups/{group_id}/carts/{cart_id}/status`：允许 `submitted->locked`（锁定收单）、`locked->draft`（解锁恢复可编辑，同时清理比它新的空占位草稿 `prune_empty_drafts`）；权限 = 该组采购员或管理员，需求人一律 403，已完成组 409。
- 批次数从组详情/工作台聚合输出：`group_detail_payload` 的 `batches` 列表带 `batch_no/cart_id/status/count/submitted_at/locked_at`，条目级带 `batch_no/cart_status`。
- **修复同会话关系陈旧 bug**：`submit_my_cart` 此前只写 `cart.group_id`，未同步 `cart.group` 关系（加载时仍为 None），导致封板后 `ensure_next_draft` 被 `cart.group is None` 守卫短路、不自动开下一批草稿（冒烟 3 项失败定位到此）。修复：写 FK 的同时显式 `cart.group = target_group` 保持关系一致。

前端：
- purchaser.html：组卡片按成员/批次渲染「第 N 批」+ 状态徽章 + 件数，「锁定该批 / 解锁（可编辑）」按钮走组内批次端点。
- member.html：成员清单按批次分组展示（`第 N 批`，头部带提交/封板时间），采购员（本组创建者）与管理员可锁定/解锁每批。
- admin.html：采购清单视图展示归属 chip「组名 · 第 N 批」，组视图沿用批次聚合。

验证：
- 后端 Python、冒烟脚本语法检查通过；镜像重建启动成功；`/health` 返回 ok。
- `scripts/smoke_test.sh` 新增 8.55 批次机制段（封板批次号递增、自动下一批空草稿、组内锁定/解锁、多批聚合、越权与状态机护栏等断言）。
- 全量冒烟测试：**261 项通过，0 项失败**（此前基线 213）。

### 2026-09-06 — 工作台布局与可访问性优化

- 统一管理员与采购员价格分组的桌面、平板和手机网格结构，移动端按名称、参数、操作的顺序自然降级。
- 为全站键盘操作增加 `:focus-visible` 焦点环、按钮按下反馈和窄屏通知布局；为减少动态干扰的用户关闭 Logo 与界面动效。
- 登录错误、链接解析结果和各角色页面通知增加辅助工具播报语义；登录表单补充 `name` 与动态入口改为语义化按钮。
- 商品缩略图和解析结果图片补充商品名称 `alt` 与懒加载，减少图片不可识别的问题。
- 为邀请码、管理员建号、建组和价格参数输入补充自动完成/输入模式提示。

验证结果：前端脚本、页面内嵌脚本和静态 UI 断言通过；Docker 镜像重建启动成功；全量冒烟测试 213 项通过、0 项失败。

### 2026-09-05 — 价格口径统一与用户只读价格框

按需求将商品价格统一按「添加商品时录入的税前原价」处理：

- 后端 `effective_price` 统一计算：税前价 = 原价；含税价 = 原价 × (1 + 价格组税率)；人民币价按含税价 × 日元汇率折算。
- 保留旧 `tax_included` 字段和接口更新能力以兼容既有数据库/客户端，但该字段不再改变价格计算结果。
- 商品库、用户清单、采购员/管理员组内清单、成员清单统一展示税前单价、含税价、人民币价。
- 用户页的三个价格框均为只读 HTML 展示，不提供任何修改控件；采购员/管理员的价格分组编辑布局保持统一网格结构。
- 清单金额合计改按含税价计算，人民币合计继续按含税价折算结果计算。

验证结果：
- 后端 Python、前端 5 页内嵌脚本、冒烟脚本语法检查通过。
- Docker 镜像重建并启动成功，API `/health` 返回 `{"status":"ok"}`。
- 全量冒烟测试：**213 项通过，0 项失败**。

### 2026-09-05 21:15 — 节点快照 v0.2（冻结基线）

按用户需求「当前保存一个节点」建立冻结快照，作为后续问题修复的回滚基线。

- 快照目录：`backups/procurement-app/2026-09-05_v0.2-node`（rsync 全量 47 个源码文件 + `MANIFEST.sha256` 51 条校验通过 + `NODE.md`）。
- 附加归档：本地数据库快照 `snapshot/local-db-20260905.dump` 与统计 `snapshot/db-state.txt`；云服务器成品包 `release-procurement-app-cloud-v0.2-20260905.tar.gz`。
- 快照时本地数据库状态：1 用户（admin@example.com / ADMIN）、3 商品、2 清单、3 条目、0 出游采购组、7 条审计事件。
- 快照时上云状态：腾讯云 + 宝塔，域名 `buy.lydsars.online`，目录 `/home/ubuntu/outbuy`，用 `docker-compose.cloud.yml` + `--env-file .env.cloud`，服务器上已移除 caddy、frontend 绑定 `127.0.0.1:8080:80` 由宝塔 Nginx 反代。
- `NODE.md` 中登记了 5 项待修复问题（管理员 bootstrap 仅首次生效、注册密码 ≥10 位与管理员建号 ≥6 位不一致且前端错误显示 `[object Object]`、`down -v` 后 DATABASE_URL 未同步导致 InvalidPasswordError、frontend `wget --spider` 健康检查恒 unhealthy、8080 端口冲突）。
- 一致性校验：`diff -rq` 显示快照与工作目录仅差两个被排除的构建日志（`build.log`、`build-api.log`）。

### 2026-09-05 — 云部署准备与实验数据清理

- 新增根目录独立生产编排：`docker-compose.cloud.yml`；新增环境变量模板 `.env.cloud.example` 与部署手册 `DEPLOY-CLOUD.md`。
- 生产编排使用 Caddy 自动 HTTPS，仅暴露 80/443；PostgreSQL、Redis、crawl 数据和 Caddy 状态使用命名卷持久化。
- 修正 `deploy/backup.sh`：显式使用生产 Compose 与 `.env.production`，避免从项目根目录运行时误用开发配置。
- 更新根 `README.md` 与 `.gitignore`，补齐当前功能和生产部署说明，并忽略云/生产环境密钥文件。
- 清理本地实验数据库：删除全部非管理员账号及其清单、商品组、旧批次、关联审计数据，仅保留 `admin@example.com`；清理前备份为 `backups/pre-clean-20260905.dump`。
- 校验结果：三份 Compose 配置解析通过，Shell/前端脚本语法检查通过；当前数据库仅 1 个管理员、2 张管理员清单、3 个管理员商品、7 条管理员审计事件。

### 2026-09-05 — 登录页 Logo 专属放大 + 副标题改为「顺手的事」

按用户需求：登录页（login.html）Logo 更大，中间副标题「内部集中采购系统」→「顺手的事」。

- 副标题：`<div class="sub">内部集中采购系统</div>` → `<div class="sub">顺手的事</div>`。
- Logo 专属放大：responsive.css Logo 区块末尾追加 `.pg-login` 作用域规则（桌面 38px/图标50px，≤760 30px/40px，≤560 26px/34px），登录页比全局 26px 明显更大；其它 4 页不受影响（仍 26px）。

验证（agent-browser）：
- 登录页桌面 brand 字号 38px、图标 50px、居中 centerOffset=0、无溢出；375px 窄屏 26px/34px 无溢出。
- 副标题文本 = 「顺手的事」。
- 其它页（index/admin/member）实测 brand 仍 26px（作用域未泄漏）。

跟进（用户「不够大，改成70px」）：桌面档加大到 70px/图标92px，≤760 52px/68px，≤560 42px/54px；实测桌面 font=70px、ico=92px、居中 center=0 无溢出；375px brand 297px < 卡宽 343px 不超、无横向溢出。

### 2026-09-05 — 品牌 Logo 重新设计：动感科技感 + 放大

按用户需求「重新设计 logo 样式，使其富有动感与科技感，并且适当放大」。保持品牌名「买办」（纯文字 + 动效化）。

设计（纯内联 SVG + CSS，无外部图片/字体资源，避开 nginx COPY 与 CDN 依赖）：
- **结构**：5 页 `.brand` 由纯文本 `<div class="brand">买办</div>` 改为 `<div class="brand">` + `svg.brand-ico`（40×40 viewBox）+ `span.brand-txt 买办`。
- **图标（动感）**：绿色渐变（#33a97c→#185f49）虚线轨道圆环 `stroke-dasharray`（26s 慢速旋转）→ 内层细环（静态，视觉层次）→ 中央「上升箭头」（竖线 + 箭头部实心）寓意采购上行/出货；金色亮点 `#f0b429` 沿环 3.2s 快速公转（SMIL `animateTransform`，2 个 rotate 动画，无需 JS/CSS transform 兼容性顾虑）。
- **文字（科技感）**：`.brand-txt` 用渐变背景 `linear-gradient(100deg,#155a43→#2fa377→#8fdcc0→#2fa377→#155a43)` + `background-clip:text;color:transparent` + `background-size:220%` + `brandShimmer` 5.5s 流光扫过动画。
- **放大**：字号 18px → **26px**（桌面），图标 34px；≤760 降到 22px/29px，≤560 降到 20px/26px（responsive.css 末尾追加，覆盖各页内联 `.brand`/`.brand span`）。
- login 页品牌在卡片顶部居中：`.pg-login .brand { justify-content:center }`。

验证（agent-browser 实测）：
- 5 页（login/index/admin/purchaser/member）brand-txt/ico/bgrad 各 1 组无重复 id；served 页面 brand-txt 存在。
- login：brand 334×34 居中（centerOffset=0px），文字 `background-clip:text` + 透明色 + 220% bg，`brandShimmer` 动画名生效，SMIL animateTransform 2 个。
- 桌面 1440：brand 26px/ico 34px；admin header brand 右缘 126 vs account 左缘 1255 无重叠；375px 窄屏 font 20px/ico 26px、无横向溢出，header 换行合理（高 33px）。
- index/member 1440px 及 index 375px 均无横向溢出。

### 2026-09-05 — 定版前全量验收：冒烟 212 项全绿 + 5 页浏览器回归通过

按用户要求「跑一次测试一下」做定版前最终验收。**冒烟测试脚本同步修正 8.6 段断言**（此前失败 8 项非产品 bug，是脚本断言仍停留在「转停用」旧语义）。

冒烟测试脚本修正（scripts/smoke_test.sh 8.6 用户管理段）：
- 删除语义断言由「转停用」改为「**彻底删除**」：`删除有记录用户转停用 200` → `删除有记录用户彻底删除 200`（仍 200）；`action=deactivated` → `action=deleted`；`停用账号登录被拒 403` → `被删账号登录被拒 401`；删除「重新启用账号 200 / PATCH active / 启用后登录恢复 200」整套旧断言（v0.2 起账号删了即不可恢复，无 active 端点）。
- 「有成员的分组拒绝删除 400 / 清空归属 200 / 无成员分组可删除 200 / 删除分组 ok」**测试顺序前移到删除用户之前**（旧顺序在用户删除后才测分组，导致 U1 已消失、断言失效）。

验收结果：
- **冒烟测试：212 项通过，0 失败**（全绿）。当前基线 = 212（此前 214 为「停用语义」项数，改「彻底删除」后少 2 个旧断言，属预期）。
- **浏览器 5 页回归（agent-browser）全通过**：
  - login：品牌「买办」居中，标题正常。
  - index（用户首页）：品牌「买办」；清单分组卡（归档组 E2E九月出游/待处理/未采购/撤回）；「我的出游采购组」面板组 chip 带**复制邀请链接**按钮；缩略图点击放大闭环（open→×close）OK。
  - admin（管理台）：4 个 tab 全验——采购清单缩略图放大 OK；商品库 78 行 **p-stock=0**、全文无「库存」；出游采购组 21 卡（邀请码/复制邀请链接/采购勾选/完成/删除）；用户与设置 123 行 avatar-btn 可点头像弹窗「冒烟测试的采购清单」（草稿+采购成功双卡），删除用户 confirm 文案含「⚠️ 彻底删除/不可恢复/组转管理员代管」，ucm-mask 仍在 body 直下。
  - purchaser（采购员工作台）：品牌「买办」；配额「还可创建 3 个组」；实测建组「回归测试出游组」→ 邀请码 6532、`inviteLink`=`http://localhost:8080/login.html?invite=6532`、复制邀请链接按钮、配额降为 2。
  - member（成员清单页）：品牌「买办」；返回链按角色切「← 返回管理台」；4 统计卡（条目/未采购/已确认/金额 ¥1,500 円≈¥72）；条目+勾选渲染正常。
- 测试数据已清理：临时组 32（204）、临时 purchaser 180（彻底删除），无残留。

### 2026-09-05 — 品牌名 SUPPLY → 买办

按用户需求「把SUPPLY替换掉，就叫（买办）」。用户确认品牌为纯文字「买办」，去掉原有末尾绿色句点。

- 前端 5 个页面（index/login/admin/purchaser/member）`<div class="brand">SUPPLY<span>.</span></div>` 统一替换为 `<div class="brand">买办</div>`（去掉绿色 `span.`）。
- 后端 `FastAPI(title="Supply Procurement API")` → `FastAPI(title="买办 Procurement API")`（main.py:560）。
- README 标题 `# Supply Procurement MVP` → `# 买办 Procurement System`。

验证：
- 全站 grep 无 `SUPPLY|Supply|supply` 残留。
- 重建 frontend 镜像（`package` 进镜像）+ api/worker（`build: ./backend` 也是打进镜像，**必须 re-build 而非仅 restart**，restart 仍跑旧代码）后：served 页面 brand 显示「买办」；`/openapi.json` title = `买办 Procurement API`。
- agent-browser：登录页与 admin 台左上角品牌均为「买办」，居中正常、无残留绿点，布局无错位。

### 2026-09-05 — 移除商品库「库存充足/剩余件数」展示列

按用户需求「删除商品库里的库存充足什么的选项，不需要」：管理台「商品库」标签每行的库存状态说明（`库存充足` / `剩 N 件`）整列移除。

- `admin.html` 渲染函数 `renderProducts()`：删除 `.p-stock` 区块行（原 `p.stock_count == null ? "库存充足" : (p.stock_count > 20 ? "库存充足" : "剩 N 件")`）。
- 列数收敛：`.prod-item` 基础 `grid-template-columns` 由 6 列 `20px 44px minmax(0,1fr) auto auto auto`（checkbox/缩略图/名称/价格/库存/操作）改为 5 列 `20px 44px minmax(0,1fr) auto auto`（删去库存列）。
- 移动端媒体查询同步：`admin.html` 内联 `@media(max-width:720px)`、`responsive.css` 的 ≤900（第 88 行）与 ≤560（第 132 行）三处 `.prod-item` 由 4 列 `20px 40px minmax(0,1fr) auto` 改为 5 列 `20px 40px minmax(0,1fr) auto auto`；并删除 `@media(max-width:720px)` 里已无意义的 `.p-stock { display:none }`。
- 后端 `Product.stock_count` 字段与 `stock_count` 相关 payload/入参**保留未删**（前端不再展示，不影响采集入库；避免动模型/迁移）。

验证：`node --check` admin.html 内联 JS 通过；重建 frontend 镜像后，浏览器（角色=admin）商品库标签实测：`.prod-item` 数量 66、`.p-stock` 数量 0，首行文本 `11 | 111 | 手工添加 · JPY | ¥ 1 円 ≈ ¥ 0.05 | 税后 | 改价 | 删除`，截图 /tmp/prod_no_stock.png 确认布局正常无空列/错位；served admin.html `p-stock`=0、grid 均为 5 列。

### 2026-09-05 — 商品缩略图点击放大（全站灯箱）

按用户需求「点击商品略缩图会放大」：全站任意商品缩略图点击即可弹出大图。

方案：做成**全站公用灯箱**，挂在共享 `auth.js`（五页 index/login/admin/purchaser/member 均已引入），并非逐页复制。

- `auth.js` 末尾新增 `initImageZoom()/openZoom()/closeZoom()`：初始化时向 `<body>` 注入 `.zoom-mask`（fixed 半透明遮罩 + 放大图 `.zoom-img` + 关闭按钮 `.zoom-close` + 说明文字 `.zoom-cap`），并绑定「点遮罩/×/Esc 关闭」。用**事件委托**在 `document` 上监听 click：命中 `<span data-ini>` 内 `<img>` 才放大（`data-ini` 是缩略图容器标记）。
- 兼容性：缩略图函数 `productThumb/itemThumb/itemThumbOptional` 本就输出 `<span data-ini>` 包裹 `<img>`，故**无需改各页渲染代码**；`thumbError` 回退的纯首字母块（无 img）自然不触发放大。
- 负向过滤：普通图片（如头像/logo，不在 `data-ini` span 内）点击不放大，避免误触。
- `responsive.css` 追加 `.zoom-mask/.zoom-img/.zoom-close/.zoom-cap` 全局样式（fade 过渡、居中放大、圆角阴影、≤560px 微调），放在媒体查询之外（覆盖所有视口）。

验证（agent-browser 实测 admin.html）：
- 采购清单 tab 点缩略图 → `.zoom-mask.show` 生效，大图 src = 缩略图 src，截图 /tmp/zoom_open.png 确认（居中放大 + 右上 ×）。
- × 按钮关闭 OK；Esc（window 级 keydown）关闭 OK；点遮罩关闭 OK。
- 注入无 `data-ini` 的普通 `<img>` 点击 → mask 不显示（**未误触发**）。
- index.html 亦加载到 zoom 函数与 mask（全站通用）。

### 2026-09-05 — 采购确认框收敛为单框 + 采购侧备注（仅采购/管理员可编辑）

按用户需求：采购员视角每个商品只保留一个确认框；该框只有采购员/管理员可改；并给每个已提交商品加一个「只有采购/管理员能编辑、用户只能看」的备注框。

后端：
- 新增 Alembic 迁移 `0006_cart_item_procurement_remark.py`（revises 0005）：`cart_items` 加列 `procurement_remark TEXT NULL`（采购侧备注，与需求人填写的 Product.remark 分开）。api 容器启动自动 `alembic upgrade head` 落库。
- 新增 `PATCH /api/admin/cart-items/{item_id}/remark`（body `{remark}`，ProcurementRemarkRequest 已存在，max 2000 字符）。权限与 confirmed/purchased 一致：管理员可改任意条目；采购员仅可改自己创建出游组内条目；普通用户（需求人）调本端点返回 403，只能只读。
- `cart_payload` 与 `group_detail_payload` 的条目字典均输出 `procurement_remark`，需求人读自己清单（/api/carts/me 与 /api/groups/me）也能读到（只读）。
- 说明：`purchase_confirmed`（确认采购）字段与 `/confirmed` 端点**保留未删**（后端兼容），只是前端不再使用。

前端五页：
- purchaser.html：`pChecks()` 去掉「确认采购」只保留「已采购」单勾选；`pSubRow()` 每条已提交商品显示可编辑备注 textarea（`.p-remark`），`onchange` 调 `saveRemark` → `PATCH /remark`。
- admin.html：出游组视图 `gCheckCell()` 与采购清单视图 `adminChecks()` 去掉「确认」只保留「采购」勾选；`gPlainRow`/`gSubRow`/`renderAdminPlain`/`renderAdminSubRow` 接入可编辑备注 textarea（`.gi-remark`），调 `saveRemark`。
- member.html：`checks()` 去掉「确认采购」只保留「已采购」；`rowHtml`/`subRowHtml` 接入可编辑备注 textarea（`.p-remark`），调 `saveRemark`。
- index.html（用户首页）：`statusChips()` 改为只跟随 `purchased`（`已采购` / `未采购`，去掉「已确认采购」「待确认」）；已提交商品（非草稿 `!isDraft`）显示只读采购备注 `采购备注：xxx`（`.proc-note`），**无勾选框、无可编辑备注框**（用户纯只读）。

验证：
- 三角色 token 实测 remark 端点：admin PATCH 200；采购员(组17拥有者) PATCH 200；普通用户 PATCH 403（`只能编辑自己创建的出游组内的条目备注`）。
- 用户读自己清单（/api/carts/me）能读到 item 134 的 procurement_remark。
- agent-browser 全链路：admin 出游组视图 `.gi-check` 仅「采购」单框（confCount=0）、备注框可编辑保存回显；purchaser 工作台 3 个「已采购」单框 + 备注框带值；member 页单「已采购」+ 备注；index 用户页仅「未采购」标签 + 只读采购备注，checkboxes=0 / textareas=0。
- 迁移 `0005 -> 0006` 日志确认；`cart_items` 已含 `procurement_remark text` 列；api /health 200。
- 附件截图：/tmp/admin_group_remark.png、/tmp/purchaser_remark.png、/tmp/member_remark.png、/tmp/index_user_remark.png。

首页手工商品与变体布局修复（2026-09-05）：
- 补齐 `index.html` 中手工表单、颜色/型号变体行、多颜色清单分组卡及状态 chip 的缺失样式，避免回退到浏览器裸布局。
- 手机端：名称/类型改为单列，解析结果按钮独占整行，多颜色子行分层排列；Pad/桌面保留双列录入。
- 新建回滚节点：`backups/procurement-app/2026-09-05_v0.2b-node/`，46 个文件，MANIFEST 校验通过。
- 验证：首页在 390/768/1100/1440px 均无横向溢出；390px 手工表单单列，768px 及桌面双列，关键输入/变体/提交按钮未越界。

成员清单页（member.html）顶部统计区错位修复（2026-09-05）：
- 现象：4 张统计卡中「金额合计」卡明显撑高，`≈ CNY` 换算值掉到卡片下方、被圆角白底框住。
- 根因：`.stat .cny` 是 `<div>`（块级），在 flex 项 `.stat` 内默认 `display:block` 铺满整行，把统计卡撑成两行（h71 vs 其余 h35）并触发 flex 容器换行错位。
- 修复：`.stat .cny` 改为 `display:inline; margin-left:5px`，让 ≈CNY 与主金额同行内联；重建 frontend 镜像，实测 4 卡 `top=215` 同行、`h=35` 一致。
- 复用要点：统计卡内做 ≈CNY 换算的 `.cny` 一律用 `inline`/`inline-block`，禁用块级，否则撑高 flex 项并换行错位。

- 起点：2026-09-04，v0.1 基线冻结并备份（见 `workbuddy/backups/procurement-app/2026-09-04_v0.1-node/`）。
- 本节点之后的所有修改均记入此小节，条目格式：`- 日期 描述`。

### 2026-09-04 — 出游采购组（替换采购批次）

数据模型：
- 新增 `ProcurementGroup`（id/title/purchaser/invite_code 4位/start_date/end_date/status/completed_at）+ `group_members` 关联表。
- `User.procurement_groups` 多对多；`Cart.group_id` 指向当前归组的组。
- 新增 `GroupStatus(str, enum.Enum)`：OPEN/COMPLETED（小写值），枚举名 PG 存 "OPEN"/"COMPLETED"。
- 旧 `procurement_batches` / `CartItem.batch_id` / `BatchStatus` 全部移除，库内表保留但代码不再引用。
- Alembic 0005 迁移：`procurement_groups`、`group_members`、`carts.group_id` + 索引；枚举仅列声明避免重复。

后端：
- 新端点：`/api/groups`（admin 全部含条目）、`/api/groups/me`（采购员/成员视角）、`/api/groups/{id}/members`（批量拉人）、`/api/groups/join`（邀请码自助加入）、`/api/groups/member-options`、`PATCH /api/groups/{id}`（改标题/日期/标记完成）、`DELETE /api/groups/{id}`（无归组清单才可删）。
- 提交清单 `POST /api/carts/me/submit` 改为接收 `CartSubmitRequest`：用户无进行中组 422 / 多个进行中组必须显式选 / 单组自动归组；body 改为可选，兼容旧调用直接 POST。
- 采购员勾选 / 确认采购改为按 `cart.group.purchaser_id` 鉴权；管理员仍可代管任意组；需求人侧只读可见确认采购状态。
- **关键修复**：`load_cart` 与 `load_group` 加 `populate_existing=True`，解决同一会话内 identity map 复用的 Cart/Group 实例在 commit 后关系属性陈旧导致 `cart.group` 返回旧值/None（expiry/expire_all 又会触发 async `MissingGreenlet`，故只能显式强制从 DB 刷新）。
- 删除用户的保护条件改为 `has_cart or has_event or has_owned_group or has_membership`。

前端：
- 管理台「采购批次」标签 → 「出游采购组」只读视图：组卡片（标题/采购员/起止日期/邀请码可复制/成员 chips/状态徽章/组内条目按 product+requester 分组渲染/确认+采购双勾选）；可代管「标记完成」「删除」；搜索+状态过滤+汇总计数。
- 采购员工作台重写：建组表单（标题 + 开始/结束日期 + 配额提示）、邀请码可一键复制、成员拉人面板（候选 chip 多选 + 批量加入）、完成 / 删除收口。
- 需求人「我的清单」页新增「我的出游采购组」面板（列出所在进行中组 + 邀请码输入加入）、草稿状态下若无可用进行中组置灰提交按钮、已提交/锁定显示归属组标签；多组时显示下拉选择目标组。
- 提交端点改用新签名，传递 `group_id`。

测试与文档：
- `scripts/smoke_test.sh` 全面改造：从 162 项扩到 **214 项全绿**，覆盖 1~9 全部业务链路；新增 4.5 出游组准备、5 归组提交、8 出游组进阶（批量拉人 / 到期停收 / 多组选择 / 越权 / 完成 / 删除）。
- 浏览器端到端（admin/purchaser/index 三页面）验证：建组 → 邀请码 → 拉人 → 提交归组 → 跨角色只读视图，全链路渲染正确。
- 工作记忆沉淀：`load_cart/load_group` 必须 `populate_existing=True`；ORM 关系不要用直接 FK 写后依赖旧实例缓存；`expire_all()` 在 `expire_on_commit=False` 异步会话中会触发同步懒加载 500。

### 2026-09-05 — 成员名一键跳转成员清单（采购组颗粒度）

前端：
- 新增 `frontend/member.html` 单成员清单页（`?group_id=&member_id=`）：根据当前角色从 `/api/groups`（admin）或 `/api/groups/me`（purchaser）取数，定位组后按 `requester.id` 筛条目并按 `product.id` 分组渲染（手工添加多颜色同 product 合并为分组卡，其它链接商品单行）；支持「确认采购 / 已采购」双勾选 PATCH（后端权限复用）；顶部统计 = 条目 / 未采购 / 已确认 / 金额合计（按币种 native + ≈ CNY）；返回链接按角色自动切换文案与目标（采购员→purchaser.html / admin→admin.html）。普通 user 角色访问会被拦截跳回 index.html。
- `purchaser.html` / `admin.html` 的成员 chip 由不可点 span 改为 `<a href="member.html?group_id=...&member_id=...">`，附 hover 高亮与 title 提示；CSS 新增 `a.mchip` / `a.gmchip` 规则。

工程：
- `frontend.Dockerfile` 增加 `COPY frontend/member.html /usr/share/nginx/html/member.html`（之前逐文件 COPY 漏了新页会导致 nginx 404）。
- agent-browser 双角色端到端：采购员组卡片点 E2E用户 → member.html 显示 1 件 E2E保温杯 + 双勾选可切换统计；admin 组视图同样入口，回链自动变「← 返回管理台」。截图：`/tmp/e2e_member_page.png`、`/tmp/e2e_member_admin.png`。

### 2026-09-05 — 移动端 / 多分辨率响应式适配（5 页一次到位）

调研（GitHub）：
- 无「一键自动适配」现成程序；通用 CSS 框架（Pico/Mini/MVP class-less、Bootstrap/Bulma 全家桶）面向新项目，套进已手写完整 CSS 的存量多页系统需类名/标记重构，冲突与回归风险大；本项目离线无 CDN、nginx 单机纯静态，结论：不引第三方框架，自研共享 responsive.css（复用 GitHub 生态通行断点标准），配合浏览器设备模拟做量化回归。

实现：
- 新增 `frontend/responsive.css`（5 页 </head> 前 <link>，位于各页内联 <style> 之后以保覆盖顺序）：
  - 断点体系（>1100 零规则，桌面零影响）：≤1100 页面留白收紧 + body overflow-x 兜底；≤900 平板横屏（管理台瀑布卡 2 列、页头/汇总/筛选可换行、标签栏 overflow-x 横向滑动、表单控件字号提至 16px 防 iOS 聚焦自动缩放）；≤760 平板竖/手机（index `.layout` 双栏收单栏、管理台 1 列瀑布、组卡/条目行/建组表单/成员清单纵向化收窄）；≤560 窄手机（长文本 `word-break` 断词、最紧凑间距）。
  - **作用域化**：5 页 `<body>` 挂 `pg-login / pg-index / pg-admin / pg-purchaser / pg-member`，全部页面私有规则以 `.pg-*` 前缀书写，杜绝跨页同名类（`.item`/`.tabs`/`.filters`/`.head` 等）互相覆盖；仅页面同构部分（.page/header/.brand/.account）通用化。
- `frontend.Dockerfile` 增加 `COPY frontend/responsive.css`。
- 验证：agent-browser `set viewport` + 溢出探测器（元素右缘>视口、容器 scrollWidth>clientWidth 被裁两类）对 5 页 × 320/390/560/620/760/900/1100/1200/1440px 多档（admin 另覆盖 4 个标签视图）全量回归，全部 0 溢出 0 裁切；computed style 抽查确认 `.pg-admin` 规则真实生效（tabs overflow auto、board 1 列、head wrap）；桌面 ≥1200 零回归。
- 可回滚基线：`workbuddy/backups/procurement-app/2026-09-05_v0.2-node/`（改造前 44 文件 + NODE.md + MANIFEST.sha256 全 OK）。

## v0.1 — 2026-09-04（基线，已备份为节点）

认证与用户：
- JWT 三角色（admin / user / purchaser）；用户列表管理 / 价格分组 / 采购批次；多选批量删除；用户列表置底。

商品与图片：
- 商品库商品图上传压缩（browser-image-compression v2.0.2 本地化，无 CDN）；类别 / 备注字段。
- 手工添加商品：图片上传 + 商品类型 + 颜色选择 + 备注（可写购买位置 / 小红书攻略）。
- 变体支持：一个商品多颜色 → 1 Product + N CartItem（同 product_id 分组），采购员「确认采购」备忘勾选。

价格与解析：
- 含税 JPY × 汇率 → CNY；税率 / 汇率存 settings 表，管理台可改。
- 链接解析按 host 分发：kakaku.com（`/item/` 后任意字母前缀 K/J 等）、kitamuracamera.jp 北村相机（`/buy/item/<id>/`，税込 + 主图）。
- SSRF host 白名单；Alembic 迁移 0001 → 0004；冒烟测试 162 项全绿。
