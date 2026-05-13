"""
智能书签整理工具 - AI自主分类版本
使用Function Calling让AI自主创建和管理书签分类
"""

import sys
import json
import re
import os

# 修复 Windows 控制台 GBK 编码无法输出 emoji 的问题
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from typing import List, Dict, Optional, Tuple
from html.parser import HTMLParser
import requests
from openai import OpenAI
from datetime import datetime
import time

# 导入解析器和生成器
from bookmark_utils import BookmarkHTMLParser, ChromeBookmarkParser, BookmarkGenerator
from web_enricher import WebEnricher

# ==================== 配置文件读取 ====================
def _load_json_config_file() -> Dict:
    """
    从同目录读取 config.json（可选）。
    说明：真实密钥不要提交到 GitHub，config.json 会被 .gitignore 忽略。
    """
    try:
        cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


# ==================== 配置部分 ====================
class Config:
    """配置类"""
    FILE_CONFIG = _load_json_config_file()

    # OpenAI API配置
    # 通过环境变量注入密钥，避免把真实密钥提交到 GitHub
    API_KEY = (
        os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("API_KEY")
        or (FILE_CONFIG.get("api_key") if isinstance(FILE_CONFIG, dict) else None)
    )
    API_BASE = (
        os.environ.get("API_BASE")
        or (FILE_CONFIG.get("api_base") if isinstance(FILE_CONFIG, dict) else None)
        or "https://api.deepseek.com/v1"
    )
    MODEL = (
        os.environ.get("MODEL")
        or (FILE_CONFIG.get("model") if isinstance(FILE_CONFIG, dict) else None)
        or "deepseek-v4-flash"
    )
    
    # 请求配置
    REQUEST_TIMEOUT = 10
    MAX_CONTENT_LENGTH = 3000
    RATE_LIMIT_DELAY = 0.5
    BATCH_SIZE = 10  # 批量处理书签数量

    # ==== 文件夹依赖控制 ====
    USE_EXISTING_FOLDERS = False   # True: LLM参考现有文件夹; False: 完全基于内容设计分类

    # ==== 网页内容增强 ====
    ENABLE_WEB_ENRICHMENT = True       # 总开关：是否先获取书签页面内容再分类
    WEB_REQUEST_TIMEOUT = 60             # 单次HTTP请求超时（秒）
    MAX_CONCURRENT_FETCHES = 3          # 并发请求数
    MAX_PAGE_CONTENT_LENGTH = 500       # 提取的正文最大字符数
    ENABLE_DUCKDUCKGO_SEARCH = True    # 同时使用 DuckDuckGo 搜索补充页面信息


# ==================== AI分类系统 ====================
class AIBookmarkClassifier:
    """使用Function Calling的AI分类器"""
    
    def __init__(self, use_existing_folders=True):
        self.client = OpenAI(
            api_key=Config.API_KEY,
            base_url=Config.API_BASE
        )
        self.category_structure = {}  # 存储AI创建的分类结构
        self.use_existing_folders = use_existing_folders
        
    def get_function_definitions(self):
        """定义Function Calling的函数"""
        return [
            {
                "name": "create_category",
                "description": "创建一个新的书签分类文件夹",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category_name": {
                            "type": "string",
                            "description": "分类文件夹的名称，例如：'开发工具/前端开发'"
                        },
                        "description": {
                            "type": "string",
                            "description": "该分类的描述，说明这个分类包含什么类型的书签"
                        }
                    },
                    "required": ["category_name", "description"]
                }
            },
            {
                "name": "classify_bookmark",
                "description": "将书签分类到指定的文件夹",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "bookmark_url": {
                            "type": "string",
                            "description": "书签的URL"
                        },
                        "category_path": {
                            "type": "string",
                            "description": "分类路径，例如：'开发工具/前端开发'"
                        },
                        "reason": {
                            "type": "string",
                            "description": "分类理由"
                        }
                    },
                    "required": ["bookmark_url", "category_path"]
                }
            }
        ]
    
    def analyze_and_create_structure(self, bookmarks: List[Dict], existing_folders: List[str]) -> Dict:
        """让AI分析书签并创建分类结构"""
        
        print("\n🤖 AI正在分析书签并创建分类结构...")
        
        # 准备书签摘要（包含页面内容增强信息）
        has_enriched = any(bm.get('_enriched') for bm in bookmarks)
        sample_size = min(len(bookmarks), 120)  # 增大样本量以支持细致分类
        bookmark_summary = []
        for bm in bookmarks[:sample_size]:
            entry = {
                'name': bm['name'][:100],
                'url': bm['url'][:150],
                'current_folder': bm.get('folder', 'Root')
            }
            enriched = bm.get('_enriched')
            if enriched:
                if enriched.get('page_title'):
                    entry['page_title'] = enriched['page_title'][:100]
                if enriched.get('description'):
                    entry['description'] = enriched['description'][:200]
                if enriched.get('content_snippet'):
                    entry['content_snippet'] = enriched['content_snippet'][:200]
                if enriched.get('search_title'):
                    entry['search_title'] = enriched['search_title'][:100]
                if enriched.get('search_snippet'):
                    entry['search_snippet'] = enriched['search_snippet'][:200]
            bookmark_summary.append(entry)

        prompt = "你是一个专业的书签管理助手。请分析以下书签样本，设计一个合理细致的分类结构。\n\n"

        # 根据配置决定是否包含现有文件夹结构
        if self.use_existing_folders and existing_folders:
            prompt += f"现有文件夹结构：\n{json.dumps(existing_folders[:20], ensure_ascii=False, indent=2)}\n\n"

        enriched_note = "（含自动获取的页面信息）" if has_enriched else ""
        prompt += f"书签样本{enriched_note}（共{len(bookmarks)}个，显示前{sample_size}个）：\n"
        prompt += f"{json.dumps(bookmark_summary, ensure_ascii=False, indent=2)}\n\n"

        prompt += "请根据书签内容，设计一个清晰、细致的分类结构。要求：\n"
        prompt += "1. 分类要具体且有2-3级层次（使用 '/' 表示子分类）\n"
        prompt += "   例如不要用笼统的「游戏与娱乐」，而应细分为「游戏/STG射击」「游戏/东方Project」「游戏/模拟经营」「视频娱乐/B站」「视频娱乐/流媒体」\n"
        prompt += "   又例如不要用「开发与编程」，而应细分为「开发工具/IDE」「开发工具/GitHub」「编程语言/Python」「编程语言/前端」「运维/Linux」「运维/服务器配置」\n"

        if self.use_existing_folders:
            prompt += "2. 考虑现有文件夹结构，可以保留、合并或重新组织\n"
        else:
            prompt += "2. 完全根据书签的实际内容和用途设计分类，不要考虑现有文件夹结构\n"

        prompt += "3. 每个分类要有明确的用途\n"
        prompt += "4. 主分类建议20-40个，每个主分类下可有2-5个子分类，让同类书签尽量集中但不混杂\n"
        prompt += "5. 分类名要具体、一目了然，避免模糊的「其他」「杂项」等命名\n\n"

        prompt += """请直接返回JSON格式的分类结构：
{{
  "分类名称1": "分类描述1",
  "分类名称2": "分类描述2",
  ...
}}"""

        try:
            response = self.client.chat.completions.create(
                model=Config.MODEL,
                messages=[
                    {"role": "system", "content": "你是一个专业的信息分类专家，擅长组织和管理书签。请直接返回JSON格式的分类结构。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7
            )
            
            content = response.choices[0].message.content.strip()
            
            # 提取JSON
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                categories = json.loads(json_match.group())
                for cat_name, cat_desc in categories.items():
                    self.category_structure[cat_name] = {
                        'description': cat_desc,
                        'bookmarks': []
                    }
                print(f"✅ AI创建了 {len(self.category_structure)} 个分类")
            else:
                self._create_default_categories()
                
        except Exception as e:
            print(f"❌ AI分析失败: {str(e)}")
            self._create_default_categories()
        
        return self.category_structure
    
    def _create_default_categories(self):
        """创建默认分类（细致版）"""
        print("  使用默认分类...")
        defaults = {
            "AI服务/API中转": "AI API 中转站、Key 分发服务",
            "AI服务/LLM平台": "大语言模型对话平台、ChatGPT类工具",
            "AI服务/图像与模型": "AI图像生成、模型下载与部署",
            "开发工具/IDE与编辑器": "IDE、代码编辑器、在线开发环境",
            "开发工具/Git与代码托管": "GitHub、GitLab、代码托管平台",
            "开发工具/前端开发": "前端框架、组件库、设计资源",
            "编程语言/Python": "Python教程、库、工具",
            "编程语言/其他语言": "JS/TS/Go/Rust等编程语言资源",
            "云服务/VPS商家": "VPS 主机商、优惠信息",
            "云服务/面板与管理": "服务器面板、管理工具、监控",
            "云服务/域名与DNS": "域名注册、DNS 管理、CDN",
            "运维/Linux教程": "Linux 命令、系统管理教程",
            "运维/服务器软件": "Nginx/Apache/MySQL 等配置",
            "运维/容器与部署": "Docker、K8s、CI/CD",
            "网站建设/WordPress": "WordPress 主题、插件、教程",
            "网站建设/建站工具": "建站平台、静态网站生成器",
            "游戏/STG射击": "弹幕射击游戏、STG 社区",
            "游戏/东方Project": "东方同人游戏、资源",
            "游戏/模拟与策略": "模拟经营、策略游戏",
            "游戏/社区与资讯": "游戏论坛、资讯站",
            "视频娱乐/弹幕视频": "B站、弹幕视频网站",
            "视频娱乐/流媒体": "YouTube、Netflix 等",
            "音乐制作/DAW与插件": "FL Studio、音源、效果器",
            "音乐制作/乐理与教程": "音乐理论、制作教程",
            "资源下载/网盘": "网盘资源、下载工具",
            "资源下载/软件破解": "破解软件、注册机",
            "学习资源/在线课程": "MOOC、视频教程平台",
            "学习资源/技术文档": "技术文档、API 参考",
            "学习资源/学术与论文": "学术搜索、论文工具",
            "设计创作/图片处理": "PS 教程、在线 P 图工具",
            "设计创作/UIUX": "UI 设计、原型工具",
            "社交媒体/社区论坛": "技术社区、问答平台",
            "社交媒体/即时通讯": "IM 工具、聊天平台",
            "博客与文章/技术博客": "程序员博客、技术文章",
            "博客与文章/独立博客": "个人博客、Medium 等",
            "工具服务/在线工具": "在线转换、生成器等实用工具",
            "工具服务/账号相关": "账号注册、验证码服务",
        }
        self.category_structure = {k: {'description': v, 'bookmarks': []} for k, v in defaults.items()}
    
    CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             ".bookmark_classify_cache.json")

    def classify_bookmarks_batch(self, bookmarks: List[Dict]) -> Dict:
        """批量分类书签，每批处理后自动缓存中间态"""

        print(f"\n📚 开始分类 {len(bookmarks)} 个书签...")

        # 如果还没有分类结构，先创建
        if not self.category_structure:
            self.analyze_and_create_structure(bookmarks, [])

        # 检查是否有缓存可以恢复
        cached_bookmarks, cached_structure = self._load_cache()
        if cached_structure:
            self.category_structure = cached_structure
            print(f"   🔄 已恢复缓存: {len(cached_bookmarks)} 个书签已分类")

        # 过滤已处理的书签
        remaining = [bm for bm in bookmarks if bm['url'] not in cached_bookmarks]
        if not remaining:
            print("   ✅ 所有书签已从缓存恢复，无需重新分类")
            return self.category_structure

        print(f"   剩余待分类: {len(remaining)} 个")

        # 批量处理剩余书签
        for i in range(0, len(remaining), Config.BATCH_SIZE):
            batch = remaining[i:i + Config.BATCH_SIZE]
            try:
                self._classify_batch(batch, i)
            except Exception as e:
                print(f"  ❌ 第 {i // Config.BATCH_SIZE + 1} 批崩溃: {str(e)}")
                print(f"    将继续处理下一批...")

            # 每批完成后保存缓存（无论成败都保存）
            self._save_cache()

            if i + Config.BATCH_SIZE < len(remaining):
                time.sleep(Config.RATE_LIMIT_DELAY)

        # 分类完成，清理缓存
        self._clear_cache()
        return self.category_structure

    def _save_cache(self):
        """保存中间态到缓存文件"""
        processed_urls = set()
        for cat_data in self.category_structure.values():
            for bm in cat_data['bookmarks']:
                processed_urls.add(bm['url'])
        cache = {
            'processed_urls': list(processed_urls),
            'category_structure': {
                cat: {'description': data['description'], 'bookmarks': data['bookmarks']}
                for cat, data in self.category_structure.items()
            }
        }
        with open(self.CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False)

    def _load_cache(self):
        """从缓存文件恢复中间态"""
        try:
            with open(self.CACHE_FILE, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            return set(cache.get('processed_urls', [])), cache.get('category_structure', {})
        except (FileNotFoundError, json.JSONDecodeError):
            return set(), {}

    def _clear_cache(self):
        """删除缓存文件"""
        try:
            os.remove(self.CACHE_FILE)
        except FileNotFoundError:
            pass
    
    def _classify_batch(self, batch: List[Dict], start_idx: int):
        """分类一批书签"""
        
        print(f"\n[{start_idx + 1}-{start_idx + len(batch)}] 处理中...")
        
        # 准备批量数据（包含页面内容增强信息）
        batch_data = []
        batch_has_enriched = False
        for bm in batch:
            entry = {
                'url': bm['url'],
                'name': bm['name'][:100],
            }
            enriched = bm.get('_enriched')
            if enriched:
                batch_has_enriched = True
                if enriched.get('page_title'):
                    entry['page_title'] = enriched['page_title'][:100]
                if enriched.get('description'):
                    entry['description'] = enriched['description'][:200]
                if enriched.get('content_snippet'):
                    entry['content_snippet'] = enriched['content_snippet'][:200]
                if enriched.get('search_title'):
                    entry['search_title'] = enriched['search_title'][:100]
                if enriched.get('search_snippet'):
                    entry['search_snippet'] = enriched['search_snippet'][:200]
            batch_data.append(entry)

        categories_list = list(self.category_structure.keys())

        enriched_hint = "（包含自动获取的页面信息）" if batch_has_enriched else ""
        prompt = f"""请将以下书签分类到合适的文件夹中。

可用分类：
{json.dumps(categories_list, ensure_ascii=False, indent=2)}

待分类书签{enriched_hint}：
{json.dumps(batch_data, ensure_ascii=False, indent=2)}

请为每个书签返回最合适的分类路径。直接返回JSON格式：
{{
  "url1": "分类路径",
  "url2": "分类路径",
  ...
}}"""

        try:
            response = self.client.chat.completions.create(
                model=Config.MODEL,
                messages=[
                    {"role": "system", "content": "你是书签分类专家。请准确地将书签分类到合适的文件夹。只返回JSON，不要其他解释。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            
            content = response.choices[0].message.content.strip()
            
            # 提取JSON
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                classifications = json.loads(json_match.group())
                
                # 应用分类
                for bm in batch:
                    url = bm['url']
                    category = classifications.get(url, "其他")
                    self._ensure_category(category)
                    self.category_structure[category]['bookmarks'].append(bm)
                    print(f"  ✓ {bm['name'][:40]} -> {category}")
            else:
                self._fallback_classify(batch)

        except Exception as e:
            print(f"  ⚠ 批量分类失败: {str(e)}")
            self._fallback_classify(batch)
    
    def _ensure_category(self, category_name):
        """确保分类存在，不存在则创建"""
        if category_name not in self.category_structure:
            self.category_structure[category_name] = {
                'description': '',
                'bookmarks': [],
            }

    def _fallback_classify(self, batch: List[Dict]):
        """备用分类方法 — 基于关键词的细致分类"""
        print("  使用备用分类方法...")
        self._ensure_category("其他")

        # 细致的关键词 → 分类映射（按优先级排列）
        rules = [
            # AI服务
            (['api中转', 'api站', 'apikey', 'api key', 'chatanywhere', 'bltcy',
              'mkeai', 'openai api', 'api服务'], "AI服务/API中转"),
            (['chatgpt', 'gpt', 'claude', 'chatbox', 'llm', '大模型',
              'deepseek', 'copilot', 'chat bot'], "AI服务/LLM平台"),
            (['stability', 'midjourney', 'dall-e', 'huggingface',
              'civitai', '模型下载', 'checkpoint', 'lora'], "AI服务/图像与模型"),

            # 开发工具
            (['vscode', 'jetbrains', 'ide', '编辑器', 'intellij',
              'pycharm', 'sublime', 'notepad++'], "开发工具/IDE与编辑器"),
            (['github', 'gitlab', 'gitee', 'git', 'repo', 'repository',
              'commit', 'pull request'], "开发工具/Git与代码托管"),
            (['前端', 'frontend', 'react', 'vue', 'angular', 'css',
              'tailwind', 'bootstrap', 'component'], "开发工具/前端开发"),

            # 编程语言
            (['python', 'pip', 'pypi', 'django', 'flask', 'fastapi'], "编程语言/Python"),
            (['javascript', 'typescript', 'node', 'golang', 'rust',
              'java', 'php', 'ruby'], "编程语言/其他语言"),

            # 云服务
            (['vps', 'racknerd', 'virmach', 'host', '服务器',
              'sentris', 'bandwagon', '搬瓦工'], "云服务/VPS商家"),
            (['面板', 'cpanel', '宝塔', 'bt panel', 'aapanel',
              'aaPanel'], "云服务/面板与管理"),
            (['域名', 'domain', 'dns', 'namesilo', 'cloudflare',
              'namesilo', '.com', '.net'], "云服务/域名与DNS"),

            # 运维
            (['linux', 'centos', 'ubuntu', 'debian', 'shell',
              'bash', '命令行', '终端'], "运维/Linux教程"),
            (['nginx', 'apache', 'mysql', 'mariadb', 'php-fpm',
              'redis', '数据库'], "运维/服务器软件"),
            (['docker', 'kubernetes', 'k8s', '容器', 'container',
              'cicd', 'jenkins'], "运维/容器与部署"),

            # 网站建设
            (['wordpress', 'wp', 'bbpress'], "网站建设/WordPress"),
            (['建站', '网站', 'sitebuilder', 'hexo', 'hugo',
              'jekyll', '静态网站'], "网站建设/建站工具"),

            # 游戏
            (['shmup', 'stg', '弹幕', '射击', 'cave', '雷电',
              '怒首领蜂'], "游戏/STG射击"),
            (['东方', 'touhou', '幻想乡', 'zun'], "游戏/东方Project"),
            (['模拟', 'sim', '经营', '策略', '文明', 'factorio'], "游戏/模拟与策略"),
            (['steam', '游戏', 'game', 'gaming', '论坛',
              '攻略'], "游戏/社区与资讯"),

            # 视频娱乐
            (['bilibili', 'b站', 'bilibili', '弹幕', 'acg',
              'mad'], "视频娱乐/弹幕视频"),
            (['youtube', 'netflix', '流媒体', 'streaming',
              'twitch'], "视频娱乐/流媒体"),

            # 音乐
            (['fl studio', 'daw', '插件', 'vst', '音源',
              'ableton', 'cubase'], "音乐制作/DAW与插件"),
            (['乐理', '编曲', '混音', '作曲', '和声'], "音乐制作/乐理与教程"),

            # 资源
            (['网盘', '云盘', '百度云', '下载', '资源'], "资源下载/网盘"),
            (['破解', 'crack', '注册机', 'keygen', 'patch',
              '免安装'], "资源下载/软件破解"),

            # 学习
            (['mooc', '课程', 'course', '学堂', '公开课',
              'udemy', 'coursera'], "学习资源/在线课程"),
            (['文档', 'doc', 'api参考', '手册', 'reference',
              'documentation'], "学习资源/技术文档"),
            (['论文', '学术', 'scholar', 'sci', 'arxiv',
              'ieee'], "学习资源/学术与论文"),

            # 设计
            (['ps', 'photoshop', '图片', '图像', '修图',
              '抠图', 'gimp'], "设计创作/图片处理"),
            (['ui', 'ux', '设计', 'figma', 'sketch',
              '原型', 'mockup'], "设计创作/UIUX"),

            # 社交媒体
            (['论坛', '社区', 'stack', 'segmentfault', '知乎',
              'reddit', 'v2ex'], "社交媒体/社区论坛"),
            (['telegram', 'whatsapp', 'discord', 'slack',
              '微信', 'qq'], "社交媒体/即时通讯"),

            # 博客
            (['博客', 'blog', '阮一峰', 'ruanyifeng', '技术文章',
              'archives'], "博客与文章/技术博客"),
            (['随笔', '日记', '生活', 'medium', '个人网站'], "博客与文章/独立博客"),

            # 工具
            (['工具', '在线', '转换', '生成', '计算器',
              'saucenao', '图片搜索'], "工具服务/在线工具"),
            (['账号', '验证码', '注册', '手机号', 'sms',
              '虚拟'], "工具服务/账号相关"),
        ]

        for bm in batch:
            text = (bm['name'] + ' ' + bm['url']).lower()

            # 第一层：关键词规则匹配
            category = None
            for keywords, cat in rules:
                if any(k in text for k in keywords):
                    category = cat
                    break

            # 第二层：动态推导分类（基于域名 + 页面信息 + 书名）
            if category is None:
                category = self._derive_dynamic_category(bm)

            # 第三层：在已有分类中找最相似的（模糊匹配）
            if category is None and self.category_structure:
                category = self._find_closest_category(bm, text)

            # 最终兜底
            if category is None:
                category = "其他"

            self._ensure_category(category)
            self.category_structure[category]['bookmarks'].append(bm)
            print(f"  ✓ {bm['name'][:40]} -> {category}")

    def _derive_dynamic_category(self, bm):
        """从书签的域名、页面标题、描述中动态推导分类"""
        import re
        from urllib.parse import urlparse

        enriched = bm.get('_enriched')
        url = bm.get('url', '')

        # 从 URL 提取域名信息
        domain = ''
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # 去掉 www 前缀和常见后缀
            domain = re.sub(r'^www\.', '', domain)
            domain = domain.split('.')[0]  # 取主域名部分
        except Exception:
            pass

        # 从页面标题提取关键信息
        page_title = ''
        if enriched:
            page_title = (enriched.get('page_title') or '').lower()
        search_title = ''
        if enriched:
            search_title = (enriched.get('search_title') or '').lower()
        description = ''
        if enriched:
            description = (enriched.get('description') or '').lower()

        combined = f"{page_title} {search_title} {description}"

        # 知名站点 → 直接映射
        domain_map = {
            'zhihu': '社交媒体/社区论坛',
            'csdn': '博客与文章/技术博客',
            'jianshu': '博客与文章/独立博客',
            'juejin': '博客与文章/技术博客',
            'youtube': '视频娱乐/流媒体',
            'bilibili': '视频娱乐/弹幕视频',
            'twitter': '社交媒体/社区论坛',
            'x.com': '社交媒体/社区论坛',
            'reddit': '社交媒体/社区论坛',
            'stackoverflow': '社交媒体/社区论坛',
            'github': '开发工具/Git与代码托管',
            'pypi': '编程语言/Python',
            'npmjs': '编程语言/其他语言',
            'docker': '运维/容器与部署',
            'cloudflare': '云服务/域名与DNS',
            'aliyun': '云服务/VPS商家',
            'tencent': '云服务/VPS商家',
            'huawei': '云服务/VPS商家',
            'baidu': '工具服务/在线工具',
            'zhangxinxu': '博客与文章/技术博客',
            'liaoxuefeng': '学习资源/在线课程',
            'runoob': '学习资源/在线课程',
            'w3school': '学习资源/在线课程',
            'mdn': '学习资源/技术文档',
        }
        if domain in domain_map:
            return domain_map[domain]

        # 域名中包含已知关键词
        domain_keywords = {
            ('api', 'apikey', 'openai'): 'AI服务/API中转',
            ('ai', 'gpt', 'llm', 'chat'): 'AI服务/LLM平台',
            ('vps', 'host', 'server', 'cloud'): '云服务/VPS商家',
            ('domain', 'dns', 'name'): '云服务/域名与DNS',
            ('wordpress', 'wp', 'blog'): '网站建设/WordPress',
            ('game', 'play', 'gaming'): '游戏/社区与资讯',
            ('music', 'audio', 'sound'): '音乐制作/乐理与教程',
            ('learn', 'edu', 'course', 'teach'): '学习资源/在线课程',
            ('doc', 'docs', 'wiki', 'ref'): '学习资源/技术文档',
            ('tool', 'convert', 'generate', 'calc'): '工具服务/在线工具',
            ('design', 'ui', 'color', 'icon'): '设计创作/UIUX',
            ('image', 'photo', 'pic', 'img'): '设计创作/图片处理',
        }
        # 按词边界匹配：将域名拆分为词段，避免 'doc' 误匹配 'docker'
        domain_segments = set(re.split(r'[-_.]', domain))
        for keywords, cat in domain_keywords.items():
            if any(k in domain_segments for k in keywords):
                return cat

        # 从页面标题/搜索摘要中提取主题
        topic_patterns = [
            (['stg', 'shmup', '弹幕', '射击'], '游戏/STG射击'),
            (['东方', 'touhou'], '游戏/东方Project'),
            (['linux', 'centos', 'ubuntu', '运维'], '运维/Linux教程'),
            (['wordpress', 'wp'], '网站建设/WordPress'),
            (['python', 'django', 'flask'], '编程语言/Python'),
            (['javascript', 'react', 'vue', 'node'], '开发工具/前端开发'),
            (['docker', 'k8s', '容器'], '运维/容器与部署'),
            (['ai', '机器学习', '深度学习', '模型'], 'AI服务/LLM平台'),
            (['vps', '服务器', '主机'], '云服务/VPS商家'),
            (['域名', 'dns', 'namesilo'], '云服务/域名与DNS'),
        ]
        for keywords, cat in topic_patterns:
            if any(k in combined for k in keywords):
                return cat

        # 如果域名有意义，基于域名动态创建分类
        if domain and len(domain) > 3 and domain not in ('www', 'com', 'org'):
            # 尝试在已有分类中找包含该域名的
            for existing_cat in self.category_structure:
                if domain.lower() in existing_cat.lower():
                    return existing_cat
            # 动态创建新分类
            return f"来自/{domain}"

        return None

    def _find_closest_category(self, bm, text):
        """在已有分类中找最接近的匹配（基于文本相似度）"""
        enriched = bm.get('_enriched')
        search_text = text
        if enriched:
            search_text += ' ' + (enriched.get('page_title') or '')
            search_text += ' ' + (enriched.get('description') or '')
            search_text += ' ' + (enriched.get('search_snippet') or '')

        best_cat = None
        best_score = 0
        text_lower = search_text.lower()
        text_words = set(text_lower.split())
        for cat in self.category_structure:
            cat_lower = cat.lower()
            parts = cat_lower.replace('/', ' ').replace('-', ' ').split()
            score = 0
            for part in parts:
                if len(part) < 2:
                    continue
                # 双向匹配：分类词出现在文本中，或文本词是分类词的一部分
                if part in text_lower:
                    score += 2 if len(part) >= 4 else 1
                else:
                    for tw in text_words:
                        if len(tw) >= 2 and tw in part:
                            score += 1
                            break
            if score > best_score:
                best_score = score
                best_cat = cat

        if best_score >= 1 and best_cat:
            return best_cat
        return None


# ==================== 主程序 ====================
def main():
    print("="*70)
    print("🚀 智能书签整理工具 - AI自主分类版本")
    print("="*70)
    
    # 检查配置
    if not Config.API_KEY:
        print("\n❌ 错误: 未检测到 API 密钥")
        print("   请设置环境变量，例如：")
        print('   PowerShell: $env:DEEPSEEK_API_KEY="你的key"')
        print('   cmd: set DEEPSEEK_API_KEY=你的key')
        return
    
    # 查找书签文件
    bookmark_files = []
    for file in os.listdir('.'):
        if file.endswith('.html') or file == 'Bookmarks':
            bookmark_files.append(file)
    
    if not bookmark_files:
        print("\n❌ 未找到书签文件")
        return
    
    print(f"\n📁 找到 {len(bookmark_files)} 个书签文件:")
    for i, file in enumerate(bookmark_files, 1):
        print(f"  {i}. {file}")
    
    # 选择文件
    if len(bookmark_files) == 1:
        selected_file = bookmark_files[0]
    else:
        choice = input(f"\n请选择文件 (1-{len(bookmark_files)}): ").strip()
        try:
            selected_file = bookmark_files[int(choice) - 1]
        except:
            print("❌ 无效选择")
            return
    
    print(f"\n📖 正在加载: {selected_file}")
    
    # 解析书签
    if selected_file.endswith('.html'):
        with open(selected_file, 'r', encoding='utf-8') as f:
            parser = BookmarkHTMLParser()
            parser.feed(f.read())
            bookmarks = parser.bookmarks
            existing_folders = parser.folders
    else:
        bookmarks, existing_folders = ChromeBookmarkParser.parse(selected_file)
    
    print(f"✅ 加载了 {len(bookmarks)} 个书签")
    print(f"✅ 发现 {len(existing_folders)} 个现有文件夹")

    if not bookmarks:
        print("❌ 没有找到书签")
        return

    # ==== 可选的网页内容增强 ====
    if Config.ENABLE_WEB_ENRICHMENT:
        enricher = WebEnricher(
            request_timeout=Config.WEB_REQUEST_TIMEOUT,
            max_concurrent=Config.MAX_CONCURRENT_FETCHES,
            max_content_length=Config.MAX_PAGE_CONTENT_LENGTH,
            enable_duckduckgo_search=Config.ENABLE_DUCKDUCKGO_SEARCH
        )
        bookmarks = enricher.enrich_batch(bookmarks)

    # AI分类
    classifier = AIBookmarkClassifier(use_existing_folders=Config.USE_EXISTING_FOLDERS)
    
    # 第一步：分析并创建分类结构
    classifier.analyze_and_create_structure(bookmarks, existing_folders)
    
    # 第二步：批量分类书签
    category_structure = classifier.classify_bookmarks_batch(bookmarks)
    
    # 打印统计
    print("\n" + "="*70)
    print("📊 分类统计")
    print("="*70)
    total = sum(len(data['bookmarks']) for data in category_structure.values())
    for category, data in sorted(category_structure.items(), key=lambda x: len(x[1]['bookmarks']), reverse=True):
        count = len(data['bookmarks'])
        if count > 0:
            percentage = (count / total * 100) if total > 0 else 0
            print(f"{category:30s}: {count:4d} 个 ({percentage:5.1f}%)")
    print("="*70)
    
    # 生成文件
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    print("\n📝 生成书签文件...")
    
    # 生成HTML（可导入任何浏览器）
    html_output = f"bookmarks_organized_{timestamp}.html"
    BookmarkGenerator.generate_html(category_structure, html_output)
    
    # 生成Chrome JSON（可替换Chrome书签）
    json_output = f"Bookmarks_organized_{timestamp}"
    BookmarkGenerator.generate_chrome_json(category_structure, json_output, selected_file)
    
    print("\n" + "="*70)
    print("✨ 整理完成！")
    print("="*70)
    print("\n📌 使用说明:")
    print(f"  1. HTML文件 ({html_output}):")
    print("     - 可导入Chrome/Firefox/Edge等任何浏览器")
    print("     - 浏览器 -> 书签管理 -> 导入书签")
    print(f"\n  2. JSON文件 ({json_output}):")
    print("     - 可替换Chrome的书签文件")
    print("     - 位置: Chrome用户数据目录/Default/Bookmarks")
    print("     - 替换前请备份原文件！")
    print("\n⚠️  建议先导入HTML文件测试，确认无误后再替换JSON文件")


if __name__ == "__main__":
    main()
