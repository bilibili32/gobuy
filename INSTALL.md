# 安装指南 — 买办采购系统

这是一份面向**全新用户**的从零安装文档。按步骤操作即可在本机（或 NAS、服务器）上把「买办采购系统」跑起来。

---

## 1. 环境要求

开始前，请确认机器满足以下条件：

| 依赖 | 版本要求 | 说明 |
| --- | --- | --- |
| Docker | 20.10+ | 含 Docker Engine 与命令行工具 |
| Docker Compose | V2（`docker compose` 子命令） | 旧版 `docker-compose` 亦可 |
| 网络 | 能访问 Docker Hub | 首次启动需要拉取基础镜像 |

> Windows / macOS 请先安装并启动 **Docker Desktop**；Linux 直接安装 docker 与 compose 即可。
> 极空间等 NAS 若自带 Docker 管理界面，请确保同时具备 **docker compose** 命令或官网的「项目（Compose）」部署入口。

---

## 2. 获取源码

```bash
git clone https://gitee.com/<你的用户名>/<仓库名>.git
cd <仓库名>
```

或直接下载 ZIP 解压到本地。

---

## 3. 配置环境变量

该系统**不会**在仓库中携带任何真实密码。安装前必须新建一个 `.env` 文件（项目根目录、与 `docker-compose.yml` 同级）。

> `.env` 已被 `.gitignore` 忽略，不会污染仓库；也请你**不要将真实 `.env` 提交到任何公开仓库**。

### 3.1 新建 `.env`

在项目根目录创建 `.env` 并填入以下内容：

```bash
POSTGRES_DB=procurement
POSTGRES_USER=procurement
POSTGRES_PASSWORD=请改成强随机密码
DATABASE_URL=postgresql+asyncpg://procurement:请改成与上面一致的密码@postgres:5432/procurement
REDIS_URL=redis://redis:6379/0
JWT_SECRET=请用随机字符替换
ACCESS_TOKEN_MINUTES=480
BOOTSTRAP_ADMIN_EMAIL=admin@example.com
BOOTSTRAP_ADMIN_PASSWORD=请改成你的管理员密码
CORS_ORIGINS=http://localhost:8080

# 爬虫（価格.com）：逗号分隔关键词；留空则 worker 空闲，不自动抓取
KAKAKU_KEYWORDS=
KAKAKU_INTERVAL=10
KAKAKU_ROUND_INTERVAL=3600
CRAWL_OUTPUT_DIR=/data/crawl
```

### 3.2 字段说明与必改项

| 字段 | 必须改？ | 说明 |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | ✅ 必改 | 数据库密码，用强随机串 |
| `DATABASE_URL` | ✅ 必改 | 其中的密码**必须与** `POSTGRES_PASSWORD` **一致** |
| `JWT_SECRET` | ✅ 必改 | 签名密钥，建议 `openssl rand -hex 32` 生成 |
| `BOOTSTRAP_ADMIN_PASSWORD` | ✅ 必改 | 首次启动自动创建的管理员密码，登录后尽快更换 |
| `BOOTSTRAP_ADMIN_EMAIL` | 建议改 | 初始管理员邮箱，默认 `admin@example.com` |
| `CORS_ORIGINS` | 视情况改 | 前端访问地址；默认 `http://localhost:8080`，用 IP 访问时改成 `http://<IP>:8080` |
| `ACCESS_TOKEN_MINUTES` | 可选 | 登录态有效期（分钟），默认 480 |
| `KAKAKU_*` | 可选 | 定时爬虫关键词；留空则不抓取 |

> 💡 **安全提示**：以上密码/密钥属于敏感信息，生成后**不要写进任何文档、代码或 git 提交**。

---

## 4. 启动服务

```bash
docker compose up -d --build
```

> ⚠️ 必须带 `--build`：本项目镜像需在本地构建（代码已烘焙进镜像），仅 `restart` 不会加载新代码。

首次启动会自动：
- 拉取 `postgres:16-alpine`、`redis:7-alpine`、`python:3.12-slim`、`nginx:1.27-alpine` 基础镜像
- 执行数据库迁移、创建初始管理员

---

## 5. 访问系统

| 页面 | 地址 |
| --- | --- |
| 用户首页 | `http://localhost:8080/` |
| 管理台 | `http://localhost:8080/admin.html` |
| 采购员工作台 | `http://localhost:8080/purchaser.html` |
| 成员清单 | `http://localhost:8080/member.html` |
| API 文档 | `http://localhost:8000/docs` |
| 健康检查 | `http://localhost:8000/health` |

使用第 3 步填写的 `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` 登录管理台。

> 用局域网 IP 访问时，把 `localhost` 换成机器 IP（`http://192.168.x.x:8080`），并同步调整 `.env` 的 `CORS_ORIGINS`。`80` 端口的容器映射如需修改，请查看 `docker-compose.yml` 的 `frontend` 与 `api` 段。

---

## 6. 如何停止 / 更新

```bash
# 停止服务（保留数据）
docker compose down

# 拉取最新代码后重新构建并启动
git pull
docker compose up -d --build

# 查看日志
docker compose logs -f
```

> ⚠️ **不要使用** `docker compose down -v`：会删除数据库数据卷，丢失全部数据。

---

## 7. 常见问题（FAQ）

### Q1：启动时提示 `8080` 端口被占用
`frontend` 需要映射 `8080`，若已占用，改 `docker-compose.yml` 中 `frontend` 的 `ports`（如 `8088:80`），并同步改 `.env` 的 `CORS_ORIGINS`。

### Q2：日志出现 `KAKAKU_KEYWORDS 未配置，60 秒后重试`
这是**正常提示**，非错误。表示定时爬虫因没配关键词而空闲待命，不影响登录和使用。如想自动抓取，在 `.env` 填 `KAKAKU_KEYWORDS` 后重建。

### Q3：构建时拉取基础镜像失败 / 超时
多为网络无法访问 Docker Hub。可配置 Docker 镜像加速器（Docker Desktop → Settings → Docker Engine，或服务器 `/etc/docker/daemon.json`）后重试。

### Q4：登录密码错误
初始管理员只在**首次启动**时创建。若之前跑过且已改密码，请使用修改后的密码；忘记密码可清空数据库卷后重建（会丢数据，慎用）。

### Q5：我想在私有网络/内网使用，不对外开放
保持容器仅映射 `127.0.0.1` 或内网地址即可（默认桥接网络，外部不可直接访问内部服务）。

---

## 8. 生产部署

在云服务器上部署同样使用基础版 `docker-compose.yml`，流程与本地完全一致：`cp .env.example .env` 填入实际值，再 `docker compose up -d --build`，然后访问 `http://服务器IP:8080`。

> ⚠️ 系统本身不含 HTTPS。如需公网安全访问，请用你的 Nginx / Caddy / 宝塔面板对 `8080` 做反向代理并配置证书，本仓库不内置该部分配置。反向代理用的 `Caddyfile` 等环境相关信息，请勿在公开仓库写入真实域名。