"""価格.com (kakaku.com) 商品搜索爬虫。

只爬正规比价商品（链接形如 ``kakaku.com/item/<商品号>``，商品号前缀字母不限），过滤赞助广告
（链接含 ``/ksearch/jump``，跳转 amazon / yahoo / rakuten 联盟链接）。

搜索页编码为 shift_jis，需显式按 shift_jis 解码。

默认限频 10 秒/请求（可配置），避免对目标站点造成压力。

用法（CLI 验证）：
    python -m app.kakaku --keyword "SN7100" --max 10
    python -m app.kakaku --keyword "SSD" --max 5 --interval 10
"""
from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass
from urllib.parse import quote, urlparse

import requests
from bs4 import BeautifulSoup

SEARCH_URL = "https://search.kakaku.com/{keyword}/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# 正规商品链接特征：kakaku.com/item/<商品号>，商品号由前缀字母 + 数字组成
# （K 前缀为新式如 K0001673419，J 等为历史前缀如 J0000049821，不限定首字母）。
ITEM_URL_RE = re.compile(r"/item/[A-Za-z]\d+")


@dataclass
class ProductHit:
    """单条搜索结果（只含正规比价商品）。"""

    name: str
    price_yen: int | None
    url: str
    maker: str | None = None
    shop_count: int | None = None
    rating: float | None = None
    image_url: str | None = None


@dataclass
class ProductDetail:
    """商品详情页解析结果（来自 JSON-LD 结构化数据）。"""

    name: str
    price_yen: int | None
    currency: str
    url: str
    image_url: str | None = None
    maker: str | None = None
    rating: float | None = None
    review_count: int | None = None
    # 商品来源站点标识（kakaku / kitamura），供入库时写 source_name。
    source: str = "kakaku"


def _clean_price(text: str | None) -> int | None:
    """从「54,980〜」「2,000」等价格文本提取整数（日元）。"""
    if not text:
        return None
    m = re.search(r"\d[\d,]*", text)
    if not m:
        return None
    return int(m.group(0).replace(",", ""))


def _clean_int(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"\d+", text)
    return int(m.group(0)) if m else None


def _clean_float(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"\d+(?:\.\d+)?", text)
    return float(m.group(0)) if m else None


def _text(el, selector: str) -> str | None:
    node = el.select_one(selector)
    return node.get_text(" ", strip=True) if node else None


class KakakuScraper:
    """価格.com 搜索爬虫，内置请求间隔限频。"""

    def __init__(
        self,
        min_interval: float = 10.0,
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

    def search(self, keyword: str, max_items: int = 20) -> list[ProductHit]:
        """按关键词搜索，返回正规比价商品列表（最多 max_items 条）。"""
        self._throttle()
        url = SEARCH_URL.format(keyword=quote(keyword, safe=""))
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        html = resp.content.decode("shift_jis", errors="replace")
        return self._parse(html, max_items)

    @staticmethod
    def _validate_item_url(url: str) -> str:
        """校验链接为 kakaku.com 商品详情页，防止 SSRF 与无关链接。"""
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("仅支持 http/https 链接")
        if parsed.hostname not in {"kakaku.com", "www.kakaku.com"}:
            raise ValueError("仅支持 kakaku.com 商品详情页链接")
        if not ITEM_URL_RE.search(parsed.path or ""):
            raise ValueError("链接格式不对，应是 kakaku.com/item/ 后跟商品号的商品详情页")
        return url

    def parse_item_url(self, url: str) -> ProductDetail:
        """解析用户粘贴的商品详情页链接，返回名称/价格/缩略图等。"""
        url = self._validate_item_url(url.strip())
        self._throttle()
        resp = self.session.get(url, timeout=self.timeout, allow_redirects=False)
        if resp.status_code in (301, 302, 303, 307, 308):
            raise ValueError("链接被重定向，请直接粘贴 kakaku.com/item/ 后跟商品号的商品页地址")
        resp.raise_for_status()
        html = resp.content.decode("shift_jis", errors="replace")
        return self._parse_detail(html, url)

    @staticmethod
    def _parse_detail(html: str, url: str) -> ProductDetail:
        soup = BeautifulSoup(html, "lxml")

        # 1) 优先解析 JSON-LD（schema.org Product），字段最完整
        data: dict | None = None
        for sc in soup.find_all("script", type="application/ld+json"):
            txt = sc.string or sc.get_text()
            if not txt or "Product" not in txt:
                continue
            try:
                parsed = json.loads(txt)
            except (ValueError, TypeError):
                continue
            candidates: list = [parsed] if isinstance(parsed, dict) else []
            if isinstance(parsed, dict) and isinstance(parsed.get("@graph"), list):
                candidates = parsed["@graph"]
            for cand in candidates:
                if isinstance(cand, dict) and cand.get("@type") == "Product":
                    data = cand
                    break
            if data:
                break

        if data:
            offers = data.get("offers") or {}
            brand = data.get("brand") or {}
            rating = data.get("aggregateRating") or {}
            name = (data.get("name") or "").strip()
            if not name:
                raise ValueError("未能解析出商品名称，请确认是 kakaku.com 商品详情页")
            return ProductDetail(
                name=name,
                price_yen=_clean_price(str(offers.get("lowPrice") or "")),
                currency=offers.get("priceCurrency") or "JPY",
                url=data.get("url") or url,
                image_url=data.get("image"),
                maker=brand.get("name") if isinstance(brand, dict) else None,
                rating=_clean_float(str(rating.get("ratingValue") or "")),
                review_count=_clean_int(str(rating.get("reviewCount") or "")),
            )

        # 2) 回退：直接解析 HTML 结构
        name = (_text(soup, "h1") or "").replace("価格比較", "").strip()
        img = soup.select_one("#s-largeProductImage img")
        image_url = None
        if img:
            image_url = img.get("src") or img.get("data-src")
        price_el = soup.select_one(".p-priceList_price")
        price_yen = _clean_price(price_el.get_text(" ", strip=True)) if price_el else None
        if not name:
            raise ValueError("未能解析该页面，请确认是 kakaku.com 商品详情页")
        return ProductDetail(
            name=name,
            price_yen=price_yen,
            currency="JPY",
            url=url,
            image_url=image_url,
        )

    @staticmethod
    def _parse(html: str, max_items: int) -> list[ProductHit]:
        soup = BeautifulSoup(html, "lxml")
        hits: list[ProductHit] = []
        for item in soup.select("div.p-item"):
            link = item.select_one("a[href]")
            href = link.get("href", "") if link else ""
            # 过滤赞助广告（联盟跳转链接）
            if "/ksearch/jump" in href:
                continue
            # 只保留正规比价商品页
            if not ITEM_URL_RE.search(href):
                continue

            name = _text(item, ".p-item_name") or _text(item, ".s-item_nameWrap a")
            if not name:
                continue

            image = item.select_one(".p-item_visual img")
            hits.append(
                ProductHit(
                    name=name,
                    price_yen=_clean_price(_text(item, ".p-item_priceNum")),
                    url=href if href.startswith("http") else "https://kakaku.com" + href,
                    maker=_text(item, ".p-item_maker"),
                    shop_count=_clean_int(
                        _text(item, ".p-item_shopCounts_num")
                        or _text(item, ".p-item_shopCounts")
                    ),
                    rating=_clean_float(
                        _text(item, ".p-item_star_rating_num")
                        or _text(item, ".p-item_rate")
                    ),
                    image_url=image.get("src") or image.get("data-src") if image else None,
                )
            )
            if len(hits) >= max_items:
                break
        return hits


def _main() -> None:
    parser = argparse.ArgumentParser(description="価格.com 商品搜索爬虫（CLI）")
    parser.add_argument("--keyword", "-k", required=True, help="搜索关键词（型号/日文/英文）")
    parser.add_argument("--max", type=int, default=20, help="最多返回条数")
    parser.add_argument("--interval", type=float, default=10.0, help="请求间隔秒数")
    args = parser.parse_args()

    scraper = KakakuScraper(min_interval=args.interval)
    hits = scraper.search(args.keyword, max_items=args.max)
    print(json.dumps([asdict(h) for h in hits], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
