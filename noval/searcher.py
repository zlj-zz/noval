from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
from urllib import parse

import base64
import re

import requests
from lxml.html import fromstring


# 通用过滤常量 — 被所有 WebSearcher 子类复用
BLOCKED_DOMAINS = [
    "zhihu.com",
    "baike.baidu.com",
    "tieba.baidu.com",
    "weibo.com",
    "douban.com",
    "taobao.com",
    "jd.com",
    "youtube.com",
    "bilibili.com",
]
NOVEL_KEYWORDS = ["小说", "read", "book", "章节", "目录", "笔趣阁", "起点中文网"]
SINGLE_CHAPTER_PATTERN = re.compile(r"/\d+/\d+\.html?$")


class BaseSearcher(ABC):
    """搜索引擎抽象基类."""

    @abstractmethod
    def search(self, name: str) -> List[Tuple[str, str]]:
        """Return list of (display_text, url)."""
        pass


class WebSearcher(BaseSearcher):
    """通用网页搜索引擎基类：封装结果过滤、格式化等公共逻辑."""

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    def __init__(self, max_results: int = 20, timeout: int = 10) -> None:
        self.max_results = max_results
        self.timeout = timeout

    @abstractmethod
    def _fetch(self, query: str) -> str:
        """发送搜索请求并返回 HTML."""
        pass

    @abstractmethod
    def _resolve_url(self, href: str) -> Optional[str]:
        """解析搜索引擎跳转链接，获取真实 URL."""
        pass

    @abstractmethod
    def _iter_results(self, doc) -> List:
        """从解析后的文档中提取结果节点列表."""
        pass

    @abstractmethod
    def _extract_title_and_href(self, item) -> Tuple[Optional[str], Optional[str]]:
        """从单个结果节点中提取标题和链接."""
        pass

    def search(self, name: str) -> List[Tuple[str, str]]:
        html = self._fetch(parse.quote(f"{name} 小说"))
        return self._parse_results(html)

    def _parse_results(self, html: str) -> List[Tuple[str, str]]:
        doc = fromstring(html)
        results: List[Tuple[str, str]] = []

        for item in self._iter_results(doc):
            title, href = self._extract_title_and_href(item)
            if not title or not href:
                continue

            real_url = self._resolve_url(href)
            if not real_url:
                continue

            domain = parse.urlparse(real_url).netloc.lower()
            if any(bd in domain for bd in BLOCKED_DOMAINS):
                continue

            path = parse.urlparse(real_url).path
            if SINGLE_CHAPTER_PATTERN.search(path):
                continue

            display = f"{title}|{domain}|{self._source_tag(title)}"
            results.append((display, real_url))

            if len(results) >= self.max_results:
                break

        return results

    def _source_tag(self, title: str) -> str:
        tag = self._source_name
        if any(kw in title for kw in NOVEL_KEYWORDS):
            tag += "[小说]"
        return tag

    @property
    @abstractmethod
    def _source_name(self) -> str:
        """返回来源名称（如 '必应'、'DDG'）."""
        pass


class BingSearcher(WebSearcher):
    """必应搜索（默认）：反爬弱、结果直接给真实 URL."""

    SEARCH_URL = "https://www.bing.com/search?q={query}"
    _source_name = "必应"

    def _fetch(self, query: str) -> str:
        url = self.SEARCH_URL.format(query=query)
        resp = requests.get(url, headers=self.HEADERS, timeout=self.timeout)
        resp.raise_for_status()
        return resp.text

    def _resolve_url(self, href: str) -> Optional[str]:
        if "bing.com/ck/" in href or "bing.com/link" in href:
            parsed = parse.urlparse(href)
            query = parse.parse_qs(parsed.query)
            if "u" in query:
                encoded = query["u"][0]
                if len(encoded) > 2 and encoded[0] == "a" and encoded[1].isdigit():
                    encoded = encoded[2:]
                pad = 4 - len(encoded) % 4
                if pad != 4:
                    encoded += "=" * pad
                try:
                    return base64.b64decode(encoded).decode("utf-8")
                except Exception:
                    pass
            try:
                resp = requests.get(
                    href, headers=self.HEADERS, timeout=5,
                    allow_redirects=True, stream=True,
                )
                resp.close()
                return resp.url
            except Exception:
                return None
        return href

    def _iter_results(self, doc):
        return doc.xpath(
            '//li[contains(@class, "b_algo")] | //div[contains(@class, "b_algo")]'
        )

    def _extract_title_and_href(self, item):
        a_tags = item.xpath(".//h2/a")
        if not a_tags:
            return None, None
        title = "".join(a_tags[0].xpath(".//text()")).strip()
        href = a_tags[0].get("href", "")
        return title, href


class DuckDuckGoSearcher(WebSearcher):
    """DuckDuckGo HTML 搜索（推荐默认）：反爬极弱、小说站结果丰富."""

    SEARCH_URL = "https://html.duckduckgo.com/html/?q={query}"
    _source_name = "DDG"

    def _fetch(self, query: str) -> str:
        url = self.SEARCH_URL.format(query=query)
        resp = requests.get(url, headers=self.HEADERS, timeout=self.timeout)
        resp.raise_for_status()
        return resp.text

    def _resolve_url(self, href: str) -> Optional[str]:
        if "duckduckgo.com/l/" in href:
            parsed = parse.urlparse(href)
            query = parse.parse_qs(parsed.query)
            if "uddg" in query:
                return parse.unquote(query["uddg"][0])
            try:
                resp = requests.get(
                    href, headers=self.HEADERS, timeout=5,
                    allow_redirects=True, stream=True,
                )
                resp.close()
                return resp.url
            except Exception:
                return None
        return href

    def _iter_results(self, doc):
        return doc.xpath('//div[contains(@class, "result")]')

    def _extract_title_and_href(self, item):
        a_tags = item.xpath('.//a[@class="result__a"]')
        if not a_tags:
            return None, None
        title = "".join(a_tags[0].xpath(".//text()")).strip()
        href = a_tags[0].get("href", "")
        return title, href


class NovelSiteSearcher(BaseSearcher):
    """兼容旧逻辑：从特定小说站搜索（fallback）."""

    def __init__(self, urls: List[str], extractor, get_html_fn) -> None:
        self.urls = urls
        self.extractor = extractor
        self.get_html = get_html_fn

    def search(self, name: str) -> List[Tuple[str, str]]:
        results: List[Tuple[str, str]] = []
        for search_url in self.urls:
            html, _ = self.get_html(search_url.format(name))
            if html:
                results.extend(self.extractor.extract_search(html, name, search_url))
        return results


# 工厂函数 — 消除 main.py / tui.py 中的重复分支
SEARCHER_MAP = {
    "duckduckgo": DuckDuckGoSearcher,
    "bing": BingSearcher,
    "novel_site": NovelSiteSearcher,
}


def get_searcher(mode: str, **kwargs) -> BaseSearcher:
    """根据模式创建对应的搜索器实例.

    Args:
        mode: 'duckduckgo' | 'bing' | 'novel_site'
        **kwargs: 传递给搜索器构造函数的参数
    """
    cls = SEARCHER_MAP.get(mode)
    if cls is None:
        raise ValueError(f"Unknown search mode: {mode!r}")
    return cls(**kwargs)
