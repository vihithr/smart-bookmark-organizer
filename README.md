# 智能书签整理工具 - AI自主分类版本

使用AI自主创建分类结构并整理书签的Python工具。

## ✨ 核心特性

### 🤖 AI自主分类
- **智能分析**：AI分析现有书签和文件夹结构
- **自动创建分类**：AI自主设计合理的分类体系
- **动态扩展**：根据书签内容动态调整分类
- **批量处理**：高效处理大量书签

### 📁 多格式支持
- **输入格式**：
  - Chrome JSON格式 (`Bookmarks`)
  - Netscape HTML格式 (`.html`)
- **输出格式**：
  - HTML格式（可导入任何浏览器）
  - Chrome JSON格式（可直接替换Chrome书签文件）

### 🎯 智能特性
- 保留现有文件夹结构并优化
- 支持多级分类（如：`开发工具/前端开发`）
- 自动去重和合并相似分类
- 保留书签的图标和时间戳

## 📦 安装

```bash
pip install -r requirements.txt
```

## ⚙️ 配置
通过环境变量配置 API 密钥（不要把真实密钥写进代码或提交到 GitHub）。

```python
class Config:
    # API配置
    # 密钥会从环境变量读取（DEEPSEEK_API_KEY / OPENAI_API_KEY / API_KEY 任选其一）
    # 你无需手动在代码里填真实密钥
    API_KEY = "（由环境变量注入）"
    API_BASE = "https://api.openai.com/v1"  # 可选
    MODEL = "gpt-3.5-turbo"  # 可选
    
    # 性能配置
    BATCH_SIZE = 10  # 每批处理的书签数量
    RATE_LIMIT_DELAY = 0.5  # API请求间隔（秒）

    # ==== 文件夹依赖控制 ====
    USE_EXISTING_FOLDERS = True   # True: LLM参考现有文件夹; False: 完全基于内容设计分类

    # ==== 网页内容增强 ====
    ENABLE_WEB_ENRICHMENT = False       # 总开关：是否先获取书签页面内容再分类
    WEB_REQUEST_TIMEOUT = 5             # 单次HTTP请求超时（秒）
    MAX_CONCURRENT_FETCHES = 3          # 并发请求数
    MAX_PAGE_CONTENT_LENGTH = 500       # 提取的正文最大字符数
    ENABLE_DUCKDUCKGO_SEARCH = True    # 同时使用 DuckDuckGo 搜索补充页面信息
```

### 新增功能说明

#### 🗂️ 文件夹依赖控制 (`USE_EXISTING_FOLDERS`)

- **True（默认）**：AI会参考现有书签文件夹结构，可以保留、合并或重新组织
- **False**：AI完全忽略现有文件夹，纯粹根据书签的实际内容和用途设计分类体系

#### 🌐 网页内容增强 (`ENABLE_WEB_ENRICHMENT`)

启用后，程序会：
1. **直接抓取**：并发访问每个书签URL，提取页面标题（`<title>`）、meta描述（`<meta name="description">`/`og:description`）和正文片段
2. **DuckDuckGo 搜索**：同时通过 DuckDuckGo 搜索书签名称/URL（需安装 `duckduckgo_search` 库），获取第三方视角的网站描述
3. **结果综合**：将页面抓取和搜索结果合并，直接抓取优先（标题、描述、正文），搜索补充（搜索标题、搜索摘要），两者信息互补，为 LLM 提供更全面的上下文

```bash
# 可选：安装DuckDuckGo搜索支持
pip install ddgs>=7.0.0
# 或旧包名: pip install duckduckgo_search>=6.0.0
```

### 支持的API服务

可以使用任何OpenAI兼容的API：

```python
# OpenAI官方
API_BASE = "https://api.openai.com/v1"

# 您书签中的API中转站
API_BASE = "https://api.bltcy.ai/v1"  # 柏拉图AI
API_BASE = "https://api.mkeai.com/v1"  # MKEAI
API_BASE = "https://api.chatanywhere.tech/v1"  # ChatAnywhere
```

## 🚀 使用方法

### 基本使用

```bash
python smart_bookmark_organizer.py
```

### 工作流程

1. **自动检测书签文件**
   - 程序会扫描当前目录下的书签文件
   - 支持选择要处理的文件

2. **网页内容增强（可选）**
   - 并发访问书签URL获取页面标题、描述、正文
   - 失败时自动回退到DuckDuckGo搜索
   - 结果缓存到内存，同URL不重复请求

3. **AI分析阶段**
   - AI分析前50个书签作为样本（含页面增强信息）
   - 根据 `USE_EXISTING_FOLDERS` 决定是否参考现有文件夹结构
   - 自动创建合理的分类体系

3. **批量分类阶段**
   - 每次处理10个书签（可配置）
   - 实时显示分类进度
   - 自动处理分类失败的情况

4. **生成输出文件**
   - HTML格式：可导入任何浏览器
   - JSON格式：可替换Chrome书签文件

## 📊 输出示例

```
📊 分类统计
======================================================================
AI与机器学习                  :   15 个 ( 25.0%)
开发工具/编程                 :   12 个 ( 20.0%)
云服务/VPS                   :    8 个 ( 13.3%)
学习资源                     :    7 个 ( 11.7%)
娱乐/游戏                    :    6 个 ( 10.0%)
博客与文章                   :    5 个 (  8.3%)
其他                        :    7 个 ( 11.7%)
======================================================================
```

## 📝 输出文件说明

### 1. HTML格式 (`bookmarks_organized_YYYYMMDD_HHMMSS.html`)

**特点**：
- 标准Netscape书签格式
- 兼容所有主流浏览器
- 保留书签图标和时间戳

**导入方法**：
- Chrome: 书签管理器 → 整理 → 从HTML文件导入书签
- Firefox: 书签 → 显示所有书签 → 导入和备份 → 从HTML导入书签
- Edge: 收藏夹 → 导入收藏夹

### 2. Chrome JSON格式 (`Bookmarks_organized_YYYYMMDD_HHMMSS`)

**特点**：
- Chrome原生格式
- 完整保留所有元数据
- 可直接替换Chrome书签文件

**使用方法**：
1. 关闭Chrome浏览器
2. 备份原书签文件
3. 找到Chrome用户数据目录：
   - Windows: `%LOCALAPPDATA%\Google\Chrome\User Data\Default\Bookmarks`
   - Mac: `~/Library/Application Support/Google/Chrome/Default/Bookmarks`
   - Linux: `~/.config/google-chrome/Default/Bookmarks`
4. 用生成的文件替换原文件
5. 重启Chrome

⚠️ **重要提示**：替换前务必备份原文件！

## 🔧 高级功能

### 自定义分类逻辑

如果AI分类失败，程序会使用备用分类方法。可以在 `_fallback_classify` 方法中自定义规则：

```python
def _fallback_classify(self, batch: List[Dict]):
    for bm in batch:
        text = (bm['name'] + ' ' + bm['url']).lower()
        
        # 自定义关键词匹配
        if 'your-keyword' in text:
            category = "您的分类"
        # ...
```

### 调整批处理大小

根据API速率限制调整：

```python
BATCH_SIZE = 10  # 减小以降低API压力
RATE_LIMIT_DELAY = 1  # 增加延迟避免限流
```

### 使用Function Calling

程序已预留Function Calling接口，可以让AI更精确地创建分类：

```python
def get_function_definitions(self):
    return [
        {
            "name": "create_category",
            "description": "创建新分类",
            # ...
        }
    ]
```

## 🎨 优化建议

### 1. 分类结构优化
- AI会自动分析书签特征
- 支持2-3级分类层次
- 避免过度细分

### 2. 性能优化
- 批量处理减少API调用
- 智能缓存分类结果
- 失败自动重试机制

### 3. 准确性优化
- 提供现有文件夹结构作为参考
- 使用书签名称和URL双重分析
- 备用规则确保100%分类

## 🐛 故障排除

### API密钥错误
```
❌ 错误: 未检测到 API 密钥
```
**解决**：设置环境变量，例如：
- PowerShell：`$env:DEEPSEEK_API_KEY="你的key"`
- cmd：`set DEEPSEEK_API_KEY=你的key`

### 分类失败
```
⚠ 批量分类失败: ...
```
**解决**：
- 检查API配额
- 降低 `BATCH_SIZE`
- 增加 `RATE_LIMIT_DELAY`
- 程序会自动使用备用分类方法

### JSON解析错误
```
⚠ 使用备用分类方法...
```
**说明**：这是正常的降级处理，不影响最终结果

## 📈 与旧版本对比

| 特性 | 旧版本 | 新版本 |
|------|--------|--------|
| 分类方式 | 预定义固定分类 | AI自主创建分类 |
| 分类灵活性 | 低 | 高 |
| 现有结构 | 忽略 | 分析并优化 |
| 输出格式 | 仅报告 | 可导入的书签文件 |
| 批量处理 | 逐个处理 | 批量处理 |
| 失败处理 | 标记为"其他" | 智能备用方案 |

## 💡 使用技巧

1. **首次使用**：建议先用小批量书签测试
2. **API选择**：可以使用您书签中保存的API中转站
3. **分类调整**：生成后可以手动微调分类
4. **定期整理**：建议每月运行一次保持书签整洁

## 📄 文件结构

```
bookmarks/
├── smart_bookmark_organizer.py  # 主程序
├── bookmark_utils.py            # 工具类
├── requirements.txt             # 依赖包
├── README.md                    # 说明文档
├── Bookmarks                    # 原始书签（Chrome格式）
├── bookmarks_5_13_26.html      # 原始书签（HTML格式）
└── 输出文件/
    ├── bookmarks_organized_*.html  # 生成的HTML书签
    └── Bookmarks_organized_*       # 生成的Chrome书签
```

## 🔒 隐私说明

- 书签URL和名称会发送到LLM API进行分析
- 不会访问书签网站内容
- 建议使用私有部署的API服务
- 所有处理都在本地完成

## 📜 许可证

MIT License

## 🤝 贡献

欢迎提交Issue和Pull Request！

## 📮 联系方式

如有问题或建议，欢迎反馈。
