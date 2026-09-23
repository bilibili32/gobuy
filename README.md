# 买办 Procurement System

面向内部集中采购的动态网站：普通用户维护个人清单，采购员通过出游采购组组织收单，管理员统一查看和推进采购状态。后端为 FastAPI + PostgreSQL + Redis，前端为静态 HTML/JavaScript，由 nginx 提供服务。

## 本地启动

1. 安装并启动 Docker Desktop。
2. 在本目录复制 `.env.example` 为 `.env`，替换数据库密码、JWT 密钥和管理员密码。
3. 启动：

```bash
docker compose up -d --build
```

服务地址：

- 用户首页：`http://localhost:8080/`
- 管理台：`http://localhost:8080/admin.html`
- API 文档：`http://localhost:8000/docs`

代码变化后需要重新构建对应镜像；前端和后端代码均打包在镜像中，不能只执行 `restart`。

## 主要能力

- 登录、注册与角色：`admin`、`user`、`purchaser`。
- 商品链接解析与手工添加，支持图片、商品类型、备注及颜色/型号变体。
- 出游采购组：创建、邀请码邀请、成员管理、清单归组、完成与删除。
- 管理员查看用户清单、维护采购状态、编辑采购侧备注、维护价格税率/汇率。
- 采购清单状态：`draft -> submitted -> locked -> success/failed`；操作写入审计事件。
- 支持 kakaku.com 与 kitamuracamera.jp 的授权公开商品解析；worker 可按关键词定时采集。

## 生产部署

在云服务器上部署同样使用基础版 `docker-compose.yml`，流程与本地一致：`cp .env.example .env` 填入实际值，再 `docker compose up -d --build`。内网直接用 `http://服务器IP:8080` 访问。

系统本身不含 HTTPS。如需公网安全访问，请用你的 Nginx / Caddy / 宝塔面板对 8080 做一层反向代理并配置证书（本项目不内置该部分）。完整从零安装步骤见 [`INSTALL.md`](INSTALL.md)。
