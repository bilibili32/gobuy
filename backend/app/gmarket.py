"""Gmarket 全球版 (global.gmarket.co.kr) 韩国商品详情解析。

商品详情页 URL 形如 ``https://global.gmarket.co.kr/item?goodscode=<数字>``，
页面为 UTF-8 HTML（无 JSON-LD），关键数据从结构化 meta 与价格区提取：
- 商品名：``meta[property=og:title]``（去掉前缀 ``[Gmarket] ``）
- 价格：``span.text__price-won``（如 ￦304,000，韩元）
- 主图：``meta[property=og:image]``（// 开头需补 https:）

只接受 global.gmarket.co.kr 域内的商品详情页，防止 SSRF 与无关链接。

用法（CLI 验证）：
    python -m app.gmarket --url "https://global.gmarket.co.kr/item?goodscode=4413116888"
"""
from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .kakaku import DEFAULT_USER_AGENT, ProductDetail, _clean_price

# Gmarket 全球版允许的 host；其余域名一律拒绝。
GMARKET_HOSTS = {"global.gmarket.co.kr"}
# 正规商品详情页特征：/item 且带 goodscode 参数
GOODSCODE_RE = re.compile(r"(?:[?&]|^)goodscode=(\d+)")


class GmarketScraper:
    """Gmarket 全球版 商品详情解析，内置请求间隔限频。"""

    def __init__(
        self,
        min_interval: float = 0.0,
        timeout: float = 20.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.min_interval = min_interval
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Language": "ko,en;q=0.8",
                "Referer": "https://global.gmarket.co.kr/Home/Main",
            }
        )
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        """确保两次请求间隔 >= min_interval 秒。"""
        wait = self._last_request_at + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    @staticmethod
    def _validate_item_url(url: str) -> str:
        """校验链接为 Gmarket 商品详情页，防止 SSRF 与无关链接。"""
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("仅支持 http/https 链接")
        if parsed.hostname not in GMARKET_HOSTS:
            raise ValueError("仅支持 global.gmarket.co.kr（Gmarket 全球版）商品详情页链接")
        if not GOODSCODE_RE.search(parsed.query or ""):
            raise ValueError("链接格式不对，应是 global.gmarket.co.kr/item?goodscode= 后跟数字的商品详情页")
        return url

    def parse_item_url(self, url: str) -> ProductDetail:
        """解析 Gmarket 商品详情页，返回名称/价格/缩略图等（币种 KRW）。"""
        url = self._validate_item_url(url.strip())
        self._throttle()
        resp = self.session.get(url, timeout=self.timeout, allow_redirects=False)
        if resp.status_code in (301, 302, 303, 307, 308):
            raise ValueError("链接被重定向，请直接粘贴 global.gmarket.co.kr/item?goodscode= 开头的商品页地址")
        resp.raise_for_status()
        html = resp.content.decode("utf-8", errors="replace")
        return self._parse_detail(html, url)

    @staticmethod
    def _parse_detail(html: str, url: str) -> ProductDetail:
        soup = BeautifulSoup(html, "lxml")

        def _meta(prop: str) -> str:
            node = soup.select_one(f'meta[property="{prop}"]')
            return (node.get("content") or "").strip() if node else ""

        # 1) 商品名：og:title，去掉站点前缀
        name = re.sub(r"^\[Gmarket\]\s*", "", _meta("og:title")).strip()
        if not name:
            raise ValueError("未能解析出商品名称，请确认是 global.gmarket.co.kr 商品详情页")

        # 2) 主图：og:image（// 开头补 https:）
        image_url = None
        img = _meta("og:image")
        if img:
            image_url = ("https:" + img) if img.startswith("//") else img

        # 3) 价格：韩元价 text__price-won（如 ￦304,000），失败回退外币价
        price_el = soup.select_one("span.text__price-won") or soup.select_one("span.text__price-foreign")
        price_won = _clean_price(price_el.get_text(" ", strip=True)) if price_el else None

        return ProductDetail(
            name=name,
            price_yen=price_won,
            currency="KRW",
            url=url,
            image_url=image_url,
            maker=None,
            rating=None,
            review_count=None,
            source="gmarket",
        )


def _main() -> None:
    parser = argparse.ArgumentParser(description="Gmarket 全球版 商品详情解析（CLI）")
    parser.add_argument("--url", "-u", required=True, help="Gmarket 商品详情页链接")
    args = parser.parse_args()

    scraper = GmarketScraper()
    detail = scraper.parse_item_url(args.url)
    print(json.dumps(asdict(detail), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
