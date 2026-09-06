#!/usr/bin/env bash
# 一键部署到云服务器：校验环境 -> 校验配置 -> 构建并启动 -> 输出访问地址。
set -euo pipefail
cd "$(dirname "$0")"

ENV_FILE=".env.production"
COMPOSE="docker-compose.prod.yml"

if ! command -v docker >/dev/null 2>&1; then
  echo "错误：未检测到 Docker，请先安装 Docker（含 Compose v2 插件）。"
  exit 1
fi
docker compose version >/dev/null 2>&1 || { echo "错误：需要 Docker Compose v2（docker compose 子命令）。"; exit 1; }

if [ ! -f "$ENV_FILE" ]; then
  cp .env.production.example "$ENV_FILE"
  echo "已从模板生成 $ENV_FILE。"
  echo "请编辑 $ENV_FILE 填写必填项：DOMAIN / POSTGRES_PASSWORD / DATABASE_URL / JWT_SECRET / 管理员账号，"
  echo "然后重新运行本脚本。"
  exit 1
fi

for key in DOMAIN POSTGRES_PASSWORD DATABASE_URL JWT_SECRET; do
  if ! grep -qE "^${key}=.+" "$ENV_FILE"; then
    echo "错误：$ENV_FILE 中 ${key} 未填写。"
    exit 1
  fi
done

echo "==> 构建并启动服务（首次构建约需几分钟）..."
docker compose -f "$COMPOSE" --env-file "$ENV_FILE" up -d --build

echo "==> 等待服务就绪..."
sleep 5
docker compose -f "$COMPOSE" --env-file "$ENV_FILE" ps

DOMAIN=$(grep -E '^DOMAIN=' "$ENV_FILE" | head -1 | cut -d= -f2-)
echo ""
echo "部署完成。"
echo "  访问地址：https://$DOMAIN"
echo "  查看日志：cd $(pwd) && docker compose -f $COMPOSE --env-file $ENV_FILE logs -f"
echo "  备份数据：bash backup.sh"
