"""爬虫调度 worker：按配置的关键词周期爬取価格.com，结果 upsert 进商品库。

环境变量：
- KAKAKU_KEYWORDS：逗号分隔的关键词列表（如 "SN7100,SSD,K0001673420"）
- KAKAKU_INTERVAL：单次请求最小间隔秒数（默认 10，即 10s/次限频）
- KAKAKU_ROUND_INTERVAL：每轮抓取间隔秒数（默认 3600，即每小时一轮）
- KAKAKU_MAX_ITEMS：每个关键词最多入库条数（默认 20）
- CRAWL_OUTPUT_DIR：结果 JSON 输出目录（默认 /data/crawl，留作审计）

入库规则：按 source_url 去重 —— 已存在则更新价格/名称/缩略图与 synced_at；
不存在且价格非空则新建（source_name=kakaku、currency=JPY；价格统一按税前原价口径计算）。

支持 `--once` 参数：跑一轮即退出，便于手动触发或验证。
"""
import asyncio
import json
import logging
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from .db import SessionLocal
from .kakaku import KakakuScraper
from .models import Product

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _keywords() -> list[str]:
    raw = os.getenv("KAKAKU_KEYWORDS", "")
    return [k.strip() for k in raw.split(",") if k.strip()]


async def ingest_hits(hits: list) -> tuple[int, int]:
    """把搜索结果 upsert 进商品库，返回 (新增, 更新)。"""
    created = updated = 0
    async with SessionLocal() as session:
        for h in hits:
            if not h.url or not h.price_yen:
                continue
            existing = (
                await session.execute(select(Product).where(Product.source_url == h.url))
            ).scalar_one_or_none()
            if existing:
                existing.price_cents = h.price_yen
                if h.name:
                    existing.name = h.name
                if h.image_url:
                    existing.image_url = h.image_url
                existing.synced_at = datetime.now(timezone.utc)
                updated += 1
            else:
                session.add(
                    Product(
                        name=h.name,
                        source_name="kakaku",
                        source_url=h.url,
                        image_url=h.image_url,
                        price_cents=h.price_yen,
                        currency="JPY",
                        tax_included=True,
                    )
                )
                created += 1
        await session.commit()
    return created, updated


def _scraper() -> KakakuScraper:
    return KakakuScraper(min_interval=float(os.getenv("KAKAKU_INTERVAL", "10")))


async def _crawl_round() -> None:
    output_dir = Path(os.getenv("CRAWL_OUTPUT_DIR", "/data/crawl"))
    output_dir.mkdir(parents=True, exist_ok=True)
    max_items = int(os.getenv("KAKAKU_MAX_ITEMS", "20"))

    for kw in _keywords():
        try:
            hits = await asyncio.to_thread(_scraper().search, kw, max_items)
            created, updated = await ingest_hits(hits)
            logging.info("关键词 %r 抓到 %d 条（入库：新增 %d、更新 %d）", kw, len(hits), created, updated)
            for h in hits:
                logging.info("  %s | ¥%s | %s", h.name, h.price_yen, h.url)

            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            fname = output_dir / f"{kw}-{stamp}.json"
            fname.write_text(json.dumps([asdict(h) for h in hits], ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 —— 单关键词失败不影响其他
            logging.error("关键词 %r 爬取失败: %s", kw, exc)


async def run() -> None:
    round_interval = float(os.getenv("KAKAKU_ROUND_INTERVAL", "3600"))
    logging.info("Kakaku crawler worker started (interval=%.1fs/req, round=%.0fs)", _scraper().min_interval, round_interval)

    while True:
        if not _keywords():
            logging.warning("KAKAKU_KEYWORDS 未配置，60 秒后重试")
            await asyncio.sleep(60)
            continue
        await _crawl_round()
        await asyncio.sleep(round_interval)


async def run_once() -> None:
    if not _keywords():
        logging.error("KAKAKU_KEYWORDS 未配置，无法执行单轮抓取")
        return
    await _crawl_round()
    logging.info("单轮抓取完成")


if __name__ == "__main__":
    asyncio.run(run_once() if "--once" in sys.argv else run())
