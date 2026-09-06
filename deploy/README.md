# 部署到云服务器（Docker）

本项目提供独立完整的生产 Compose，一条命令即可部署到任何装了 Docker 的云服务器，
Caddy 自动完成 HTTPS 证书申请与续期。

## 架构

```
浏览器 ──HTTPS──> Caddy (:80/:443) ──> frontend nginx ──┬─> 静态页面
                                                        └─> /api 反代 ──> api ──> postgres / redis
```

- 对外只开放 80/443；api、frontend、postgres、redis 均不映射宿主端口，只走容器内网。
- 前端同源调用 `/api`，无跨域问题。
- 首次启动时 api 会自动执行 Alembic 建表，并创建初始管理员。

## 一、准备

1. 一台云服务器（Linux，2C2G 起步），已安装 Docker 与 Compose v2（`docker compose version` 可运行）。
2. 一个域名，A 记录解析到服务器公网 IP，并在安全组/防火墙放行 **80** 和 **443** 端口。
3. 把**整个项目目录**上传到服务器（至少包含 `backend/`、`frontend/`、`frontend.Dockerfile`、`deploy/`）。

## 二、配置

```bash
cd deploy
cp .env.production.example .env.production
vi .env.production
```

必填并修改：

| 变量 | 说明 |
|---|---|
| `DOMAIN` | 你的域名，如 `procurement.yourcorp.com` |
| `POSTGRES_PASSWORD` | 数据库密码，改强随机值 |
| `DATABASE_URL` | 其中的密码与 `POSTGRES_PASSWORD` 保持一致 |
| `JWT_SECRET` | 用 `openssl rand -hex 32` 生成 |
| `BOOTSTRAP_ADMIN_EMAIL/PASSWORD` | 初始管理员账号 |

可选：`KAKAKU_KEYWORDS` 填爬虫关键词（如 `SN7100,SSD`），填了才启用定时抓取。

## 三、部署

```bash
cd deploy
./deploy.sh
```

脚本会自动：校验环境与配置 → `docker compose up -d --build` → 输出访问地址。

手动等价命令：

```bash
cd deploy
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

首次构建需拉取基础镜像并安装依赖，约几分钟。完成后访问 `https://你的域名/`。

## 四、常用运维

```bash
cd deploy

# 查看状态 / 日志
docker compose -f docker-compose.prod.yml --env-file .env.production ps
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f api

# 更新代码后重新构建
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build

# 停止 / 完全清除（含数据卷，慎用）
docker compose -f docker-compose.prod.yml --env-file .env.production down
docker compose -f docker-compose.prod.yml --env-file .env.production down -v
```

## 五、备份与恢复

```bash
cd deploy
bash backup.sh          # 备份到 backups/，自动保留最近 30 份
```

恢复：

```bash
gunzip -c backups/procurement-YYYYMMDD-HHMMSS.sql.gz \
  | docker compose -f docker-compose.prod.yml --env-file .env.production exec -T postgres \
      psql -U procurement -d procurement
```

## 六、注意事项

- **证书**：Caddy 全自动申请/续期，无需人工干预；前提是域名已解析、80/443 已放行。
- **时区**：数据库统一存 UTC，前端按浏览器本地时区显示，无需额外配置。
- **安全**：`.env.production` 含机密，勿提交到版本库；初始管理员登录后请尽快改密。
- **无真实域名时本地验证**：把 `deploy/Caddyfile` 里 `{$DOMAIN}` 换成 `localhost` 并加一行 `tls internal`，
  即可用自签名证书跑通 HTTPS 链路。
