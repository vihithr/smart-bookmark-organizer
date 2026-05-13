"""
书签网页内容增强模块
并发获取书签 URL 的页面内容（标题/描述/正文），同时通过 DuckDuckGo 搜索补充信息
"""

import json
import os
import sys
import re as _re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# 修复 Windows 控制台 GBK 编码问题
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


class WebEnricher:
    """并发获取页面内容 + DuckDuckGo 搜索，为 LLM 分类提供综合上下文"""

    PERSISTENT_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "_enriched_cache.json")

    def __init__(self, request_timeout=5, max_concurrent=3, max_content_length=500,
                 enable_duckduckgo_search=True):
        self.session = self._create_session()
        self.request_timeout = request_timeout
        self.max_concurrent = max_concurrent
        self.max_content_length = max_content_length
        self.enable_duckduckgo_search = enable_duckduckgo_search

        self._ddgs_cls = self._get_ddgs()  # 缓存 DDGS 类，避免重复 import
        # 内存缓存（会话内快速读取）+ 文件缓存（跨会话持久化）
        self._cache = {}
        self._cache_lock = threading.Lock()
        self._load_persistent_cache()
        self._cache_dirty = False  # 标记是否有新数据需要写盘
        self._stats = {"direct_ok": 0, "direct_fail": 0, "search_ok": 0, "search_fail": 0}
        self._stats_lock = threading.Lock()

    def _create_session(self):
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        return session

    def _load_persistent_cache(self):
        """从本地文件加载持久化缓存"""
        try:
            with open(self.PERSISTENT_CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            loaded = 0
            for url, enriched in data.items():
                if url not in self._cache:
                    self._cache[url] = enriched
                    loaded += 1
            if loaded:
                print(f"📂 从本地缓存加载了 {loaded} 个 URL 的页面数据")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save_persistent_cache(self):
        """将内存缓存写入本地文件"""
        if not self._cache_dirty:
            return
        try:
            # 只保存非 None 的结果
            data = {url: v for url, v in self._cache.items() if v is not None}
            with open(self.PERSISTENT_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            self._cache_dirty = False
        except OSError as e:
            print(f"   ⚠ 缓存写盘失败: {e}")

    def enrich_batch(self, bookmarks):
        """批量增强书签，为每个 bookmark dict 附加 _enriched 字段"""
        if not bookmarks:
            return bookmarks

        to_fetch = []
        for bm in bookmarks:
            url = bm.get("url", "")
            with self._cache_lock:
                if url in self._cache:
                    bm["_enriched"] = self._cache[url]
                else:
                    to_fetch.append(bm)

        if not to_fetch:
            print(f"\n📦 所有书签内容已缓存（内存+本地文件），跳过获取")
            return bookmarks

        print(f"\n🌐 开始获取 {len(to_fetch)} 个书签的页面内容...")
        if self._cache:
            print(f"   已缓存: {len(self._cache)} 个, 待获取: {len(to_fetch)} 个")
        print(f"   并发数: {self.max_concurrent}, 超时: {self.request_timeout}s")
        if self.enable_duckduckgo_search:
            print(f"   每个书签同时进行：直接页面抓取 + DuckDuckGo 搜索")

        completed = 0
        with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
            futures = {executor.submit(self._enrich_bookmark, bm): bm for bm in to_fetch}
            for future in as_completed(futures):
                completed += 1
                if completed % 10 == 0 or completed == len(to_fetch):
                    print(f"   [{completed}/{len(to_fetch)}] 已完成")
                # 每 50 个保存一次持久化缓存
                if completed % 50 == 0:
                    self._save_persistent_cache()

        # 最终保存
        self._save_persistent_cache()
        self._print_stats()
        return bookmarks

    def _enrich_bookmark(self, bookmark):
        """并发执行页面抓取 + DuckDuckGo 搜索，综合两者结果"""
        url = bookmark.get("url", "")
        if not url or not urlparse(url).scheme.startswith("http"):
            self._cache_and_set(bookmark, url, None)
            return

        direct_result = None
        search_result = None

        # 在线程池内再开两个子任务，并行执行直接抓取和搜索
        with ThreadPoolExecutor(max_workers=2) as inner:
            direct_future = inner.submit(self._fetch_url_content, url)

            if self.enable_duckduckgo_search:
                query = bookmark.get("name", "") or url
                search_future = inner.submit(self._search_description, query)
            else:
                search_future = None

            direct_result = direct_future.result()
            if search_future:
                search_result = search_future.result()

        # 更新统计
        with self._stats_lock:
            if direct_result:
                self._stats["direct_ok"] += 1
            else:
                self._stats["direct_fail"] += 1
            if self.enable_duckduckgo_search:
                if search_result:
                    self._stats["search_ok"] += 1
                else:
                    self._stats["search_fail"] += 1

        merged = self._merge_results(direct_result, search_result)
        self._cache_and_set(bookmark, url, merged)

    def _merge_results(self, direct, search):
        """综合直接抓取和搜索的结果"""
        merged = {"sources": []}

        if direct:
            merged["page_title"] = direct.get("page_title")
            merged["description"] = direct.get("description")
            merged["content_snippet"] = direct.get("content_snippet")
            merged["sources"].append("direct")

        if search:
            merged["search_title"] = search.get("page_title")
            merged["search_snippet"] = search.get("description")
            # 直接抓取失败时用搜索结果补充基本信息
            if not merged.get("page_title"):
                merged["page_title"] = search.get("page_title")
            if not merged.get("description"):
                merged["description"] = search.get("description")
            merged["sources"].append("duckduckgo")

        if not merged.get("sources"):
            return None  # 两者都失败
        return merged

    def _cache_and_set(self, bookmark, url, result):
        bookmark["_enriched"] = result
        with self._cache_lock:
            self._cache[url] = result
            self._cache_dirty = True

    def _fetch_url_content(self, url):
        try:
            resp = self.session.get(url, timeout=self.request_timeout, stream=True)
            if resp.status_code != 200:
                return None

            content_type = resp.headers.get("Content-Type", "")
            if "html" not in content_type.lower():
                return None

            raw = b""
            max_bytes = self.max_content_length * 4
            for chunk in resp.iter_content(chunk_size=8192):
                raw += chunk
                if len(raw) >= max_bytes:
                    break
            resp.close()

            soup = BeautifulSoup(raw, "html.parser")

            page_title = None
            if soup.title and soup.title.string:
                page_title = soup.title.string.strip()[:200]

            description = None
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                description = meta_desc["content"].strip()[:300]
            og_desc = soup.find("meta", attrs={"property": "og:description"})
            if og_desc and og_desc.get("content"):
                description = og_desc["content"].strip()[:300]

            content_snippet = None
            if soup.body:
                text = soup.body.get_text(separator=" ", strip=True)
                text = _re.sub(r"\s+", " ", text)
                content_snippet = text[:self.max_content_length]

            if not page_title and not description and not content_snippet:
                return None

            return {
                "page_title": page_title,
                "description": description,
                "content_snippet": content_snippet,
            }

        except Exception:
            return None

    def _get_ddgs(self):
        """获取 DDGS 类，优先使用新包名 ddgs，回退到旧包名"""
        try:
            from ddgs import DDGS
            return DDGS
        except ImportError:
            pass
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from duckduckgo_search import DDGS
            return DDGS
        except ImportError:
            return None

    def _search_description(self, query):
        if self._ddgs_cls is None:
            return None
        try:
            results = list(self._ddgs_cls().text(query, max_results=1))
            if results:
                r = results[0]
                return {
                    "page_title": r.get("title", "")[:200],
                    "description": r.get("body", "")[:300],
                }
            return None
        except Exception:
            return None

    def _print_stats(self):
        print(f"\n📊 页面内容获取统计:")
        print(f"   直接抓取: ✅ {self._stats['direct_ok']} / ❌ {self._stats['direct_fail']}")
        if self.enable_duckduckgo_search:
            print(f"   DuckDuckGo搜索: ✅ {self._stats['search_ok']} / ❌ {self._stats['search_fail']}")
        print(f"   💾 缓存URL数: {len(self._cache)}")
