"""新宿北村写真機店 (kitamuracamera.jp) 中古商品详情解析。

商品详情页 URL 形如 ``https://www.kitamuracamera.jp/buy/item/<数字>/``，
页面为 Nuxt SSR（UTF-8，无 JSON-LD），关键数据从页面结构提取：
- 商品名：主图 ``img[alt]``（如「【中古】ソニー α6600 ボディ [ILCE-6600]」）
- 价格：``span.price-text``（如 107,300，单位「円(税込)」= 含税）
- 主图：``//nc-img.kitamura.jp/<商品id>-1-1.jpg``（需补 https:）

只接受 kitamuracamera.jp 域内的 /buy/item/ 商品详情页，防止 SSRF 与无关链接。

用法（CLI 验证）：
    python -m app.kitamura --url "https://www.kitamuracamera.jp/buy/item/2119341166424/"
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

from .kakaku import DEFAULT_USER_AGENT, ProductDetail, _clean_int, _clean_price

# 北村相机允许的 host（含 www）；其余域名一律拒绝。
KITAMURA_HOSTS = {"kitamuracamera.jp", "www.kitamuracamera.jp"}
# 正规商品详情页特征：/buy/item/<纯数字>/
ITEM_URL_RE = re.compile(r"/buy/item/\d+")


class KitamuraScraper:
    """北村写真機店 商品详情解析，内置请求间隔限频。"""

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
                "Accept-Language": "ja,en;q=0.8",
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
        """校验链接为北村相机商品详情页，防止 SSRF 与无关链接。"""
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("仅支持 http/https 链接")
        if parsed.hostname not in KITAMURA_HOSTS:
            raise ValueError("仅支持 kitamuracamera.jp（北村相机）商品详情页链接")
        if not ITEM_URL_RE.search(parsed.path or ""):
            raise ValueError("链接格式不对，应是 kitamuracamera.jp/buy/item/ 后跟数字的商品详情页")
        # 去 query/fragment，归一化 canonical URL 便于商品去重
        path = parsed.path.rstrip("/")
        return f"https://{parsed.hostname}{path}/"

    def parse_item_url(self, url: str) -> ProductDetail:
        """解析北村商品详情页，返回名称/价格/缩略图等。"""
        url = self._validate_item_url(url.strip())
        self._throttle()
        resp = self.session.get(url, timeout=self.timeout, allow_redirects=False)
        if resp.status_code in (301, 302, 303, 307, 308):
            raise ValueError("链接被重定向，请直接粘贴 kitamuracamera.jp/buy/item/ 开头的商品页地址")
        resp.raise_for_status()
        html = resp.content.decode(resp.encoding or "utf-8", errors="replace")
        return self._parse_detail(html, url)

    @staticmethod
    def _parse_detail(html: str, url: str) -> ProductDetail:
        soup = BeautifulSoup(html, "lxml")

        # 1) 商品名：主图 alt 最干净（去掉尾部编号/站点名），失败再取 title 首段
        img = soup.select_one('img[src*="nc-img.kitamura.jp"][src*="-1-1.jpg"]')
        name = ""
        if img:
            name = (img.get("alt") or "").strip()
        if not name:
            title = (soup.title.get_text(" ", strip=True) if soup.title else "") or ""
            head = title.split("|")[0].strip()
            name = re.sub(r"\[\d+\]$", "", head).strip()
        if not name:
            raise ValueError("未能解析出商品名称，请确认是北村相机商品详情页")

        # 2) 主图：//nc-img.kitamura.jp/<id>-1-1.jpg → 补 https:
        image_url = None
        if img:
            src = img.get("src") or ""
            if src.startswith("//"):
                image_url = "https:" + src
            elif src.startswith("http"):
                image_url = src

        # 3) 价格：span.price-text（含税 JPY，如 107,300）
        price_el = soup.select_one("span.price-text")
        price_yen = _clean_price(price_el.get_text(" ", strip=True)) if price_el else None

        return ProductDetail(
            name=name,
            price_yen=price_yen,
            currency="JPY",
            url=url,
            image_url=image_url,
            maker=None,
            rating=None,
            review_count=None,
            source="kitamura",
        )


def _main() -> None:
    parser = argparse.ArgumentParser(description="北村写真機店 商品详情解析（CLI）")
    parser.add_argument("--url", "-u", required=True, help="北村相机商品详情页链接")
    args = parser.parse_args()

    scraper = KitamuraScraper()
    detail = scraper.parse_item_url(args.url)
    print(json.dumps(asdict(detail), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
