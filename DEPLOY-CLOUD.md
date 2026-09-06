# 买办：云服务器 Docker 部署手册

本文使用项目根目录的 `docker-compose.cloud.yml`，与本地开发 Compose 相互独立。
生产环境只对公网开放 80/443，API、前端、PostgreSQL、Redis 均使用 Compose 内网。

> 发布包：请从源码仓库获取对应版本。生产环境变量文件只在服务器本地创建，禁止提交到仓库。

## 1. 服务器准备

建议使用 Linux 云服务器（2 vCPU / 2 GB 内存起步），安装 Docker Engine 与 Compose v2：

```bash
docker --version
docker compose version
```

将整个项目目录上传到服务器，至少包括：`backend/`、`frontend/`、`frontend.Dockerfile`、`docker-compose.cloud.yml`、`deploy/Caddyfile`。

在云平台安全组和服务器防火墙放行 TCP **80**、**443**。准备一个 A/AAAA 记录已指向服务器公网 IP 的域名；Caddy 会自动申请和续期 HTTPS 证书。

## 2. 配置生产环境

在项目根目录执行：

```bash
cp .env.cloud.example .env.cloud
chmod 600 .env.cloud
openssl rand -hex 32
vi .env.cloud
```

至少修改以下变量：

| 变量 | 要求 |
| --- | --- |
| `DOMAIN` | 实际访问域名，DNS 必须已解析到本机 |
| `POSTGRES_PASSWORD` | 强随机数据库密码 |
| `DATABASE_URL` | 连接串中的密码必须与 `POSTGRES_PASSWORD` 一致；特殊字符需 URL 编码 |
| `JWT_SECRET` | 使用 `openssl rand -hex 32` 生成的随机值 |
| `BOOTSTRAP_ADMIN_PASSWORD` | 初始管理员强密码；首次登录后按内部安全规范更换 |

`BOOTSTRAP_ADMIN_EMAIL` 请填写你自己的管理员邮箱，不要使用示例邮箱。`KAKAKU_KEYWORDS` 为空时 worker 保持空闲；只有已获授权的公开商品采集任务才填写关键词。

## 3. 校验并启动

先检查 Compose 展开结果，不启动服务：

```bash
docker compose -f docker-compose.cloud.yml --env-file .env.cloud config --quiet
```

首次部署：

```bash
docker compose -f docker-compose.cloud.yml --env-file .env.cloud up -d --build
```

API 容器入口会执行 `alembic upgrade head`，完成数据库迁移后启动 API；前端静态文件也会在镜像构建时打包。查看状态：

```bash
docker compose -f docker-compose.cloud.yml --env-file .env.cloud ps
docker compose -f docker-compose.cloud.yml --env-file .env.cloud logs -f api
```

所有服务正常后访问 `https://你的域名/`。API 文档默认路径为 `https://你的域名/docs`，如不希望公开，可在后续网关策略中限制访问。

## 4. 更新版本

上传新代码后，在项目根目录执行：

```bash
docker compose -f docker-compose.cloud.yml --env-file .env.cloud up -d --build
```

不要只执行 `restart`：后端和前端代码都 baked into image，代码变化需要重新构建镜像。更新前建议先做数据库备份。

## 5. 备份与恢复

生产 Compose 的数据库卷名为 `procurement-app_postgres_data`（实际名称以 `docker volume ls` 为准）。可直接备份：

```bash
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
docker compose -f docker-compose.cloud.yml --env-file .env.cloud exec -T postgres \
  pg_dump -U "${POSTGRES_USER:-procurement}" "${POSTGRES_DB:-procurement}" \
  | gzip > "backups/procurement-$STAMP.sql.gz"
```

恢复前先确认目标数据库和备份文件；恢复示例：

```bash
gunzip -c backups/procurement-YYYYMMDD-HHMMSS.sql.gz \
  | docker compose -f docker-compose.cloud.yml --env-file .env.cloud exec -T postgres \
      psql -U "${POSTGRES_USER:-procurement}" "${POSTGRES_DB:-procurement}"
```

不要删除 `postgres_data`、`redis_data`、`caddy_data`、`caddy_config` 卷，除非确认不再需要其中的数据。尤其不要把 `down -v` 当作普通停止命令。

## 6. 常用运维命令

```bash
# 查看全部服务状态
docker compose -f docker-compose.cloud.yml --env-file .env.cloud ps

# 查看全部日志
docker compose -f docker-compose.cloud.yml --env-file .env.cloud logs -f

# 重启单个无代码变更服务
docker compose -f docker-compose.cloud.yml --env-file .env.cloud restart worker

# 停止容器但保留卷
docker compose -f docker-compose.cloud.yml --env-file .env.cloud down

# 查看磁盘占用
docker system df
```

## 7. 安全检查清单

- `.env.cloud` 使用 `chmod 600`，不要上传到公开仓库或发到聊天工具。
- 云安全组只开放 80/443；不要额外开放 5432、6379、8000。
- `JWT_SECRET`、数据库密码、管理员密码分别使用不同随机值。
- 首次登录后检查管理员账号，并更换初始管理员密码。
- 定期将数据库备份复制到服务器以外的安全位置，并定期验证恢复流程。
- 只采集目标网站授权且允许访问的公开信息，遵守站点规则和适用法律。

## 8. 故障排查

1. **Caddy 无法签发证书**：检查 DNS、80/443 入站规则，确认域名没有指向旧服务器；查看 `caddy` 日志。
2. **API 不健康**：查看 `api` 日志，重点检查 `DATABASE_URL`、数据库密码和迁移错误。
3. **页面是旧版本**：执行 `up -d --build`，不要只重启容器；确认前端镜像已重新创建。
4. **数据库连接失败**：检查 `postgres` 是否 healthy，以及 `DATABASE_URL` 主机名是否为 `postgres`，不要写 `localhost`。
5. **回滚**：先停止更新并保留数据卷，使用上一份代码重新构建；涉及数据库迁移时先备份并评估兼容性。
