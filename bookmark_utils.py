"""
书签工具类 - 解析器和生成器
"""

import json
import time
from typing import List, Dict, Tuple
from html.parser import HTMLParser


class BookmarkHTMLParser(HTMLParser):
    """解析Netscape书签HTML格式"""
    
    def __init__(self):
        super().__init__()
        self.bookmarks = []
        self.folders = []
        self.current_folder = []
        self.current_bookmark = {}
        self.in_title = False
        
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        
        if tag == 'h3':
            self.in_title = True
        elif tag == 'a':
            self.current_bookmark = {
                'url': attrs_dict.get('href', ''),
                'name': '',
                'folder': '/'.join(self.current_folder) if self.current_folder else 'Root',
                'add_date': attrs_dict.get('add_date', ''),
                'icon': attrs_dict.get('icon', ''),
            }
            self.in_title = True
            
    def handle_endtag(self, tag):
        if tag == 'dl' and self.current_folder:
            self.current_folder.pop()
                
    def handle_data(self, data):
        data = data.strip()
        if self.in_title and data:
            if self.current_bookmark:
                self.current_bookmark['name'] = data
                self.bookmarks.append(self.current_bookmark.copy())
                self.current_bookmark = {}
                self.in_title = False
            else:
                folder_path = '/'.join(self.current_folder + [data]) if self.current_folder else data
                self.folders.append(folder_path)
                self.current_folder.append(data)
                self.in_title = False


class ChromeBookmarkParser:
    """解析Chrome JSON格式书签"""
    
    @staticmethod
    def parse(file_path: str) -> Tuple[List[Dict], List[str]]:
        """解析Chrome书签文件，返回(书签列表, 文件夹列表)"""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        bookmarks = []
        folders = []
        
        def extract_bookmarks(node, folder_path=""):
            if node.get('type') == 'url':
                bookmarks.append({
                    'url': node.get('url', ''),
                    'name': node.get('name', ''),
                    'folder': folder_path,
                    'add_date': node.get('date_added', ''),
                    'guid': node.get('guid', ''),
                })
            elif node.get('type') == 'folder':
                folder_name = node.get('name', '')
                new_path = f"{folder_path}/{folder_name}" if folder_path else folder_name
                folders.append(new_path)
                for child in node.get('children', []):
                    extract_bookmarks(child, new_path)
        
        for root_name, root_node in data.get('roots', {}).items():
            if isinstance(root_node, dict) and 'children' in root_node:
                for child in root_node['children']:
                    extract_bookmarks(child, root_name)
        
        return bookmarks, folders


class BookmarkGenerator:
    """生成可导入的书签文件"""
    
    @staticmethod
    def generate_html(category_structure: Dict, output_path: str):
        """生成Netscape HTML格式书签文件"""
        
        html = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<!-- This is an automatically generated file.
     It will be read and overwritten.
     DO NOT EDIT! -->
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
"""
        
        # 按分类组织
        for category, data in sorted(category_structure.items()):
            bookmarks = data['bookmarks']
            if not bookmarks:
                continue
            
            # 处理多级分类
            parts = category.split('/')
            indent = '    '
            
            # 创建文件夹层次
            for i, part in enumerate(parts):
                html += f'{indent * (i + 1)}<DT><H3 ADD_DATE="{int(time.time())}" LAST_MODIFIED="{int(time.time())}">{part}</H3>\n'
                html += f'{indent * (i + 1)}<DL><p>\n'
            
            # 添加书签
            bookmark_indent = indent * (len(parts) + 1)
            for bm in bookmarks:
                name = bm['name'].replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
                url = bm['url'].replace('"', '&quot;')
                add_date = bm.get('add_date', str(int(time.time())))
                icon = bm.get('icon', '')
                
                icon_attr = f' ICON="{icon}"' if icon else ''
                html += f'{bookmark_indent}<DT><A HREF="{url}" ADD_DATE="{add_date}"{icon_attr}>{name}</A>\n'
            
            # 关闭文件夹
            for i in range(len(parts) - 1, -1, -1):
                html += f'{indent * (i + 1)}</DL><p>\n'
        
        html += '</DL><p>\n'
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        
        print(f"\n✅ HTML书签文件已生成: {output_path}")
        print(f"   可直接导入Chrome/Firefox/Edge等浏览器")
    
    @staticmethod
    def generate_chrome_json(category_structure: Dict, output_path: str, original_file: str = None):
        """生成Chrome JSON格式书签文件"""
        
        # 基础结构
        chrome_data = {
            "checksum": "",
            "roots": {
                "bookmark_bar": {
                    "children": [],
                    "date_added": str(int(time.time() * 1000000)),
                    "date_modified": str(int(time.time() * 1000000)),
                    "guid": "00000000-0000-4000-8000-000000000001",
                    "id": "1",
                    "name": "书签栏",
                    "type": "folder"
                },
                "other": {
                    "children": [],
                    "date_added": str(int(time.time() * 1000000)),
                    "date_modified": str(int(time.time() * 1000000)),
                    "guid": "00000000-0000-4000-8000-000000000002",
                    "id": "2",
                    "name": "其他书签",
                    "type": "folder"
                },
                "synced": {
                    "children": [],
                    "date_added": str(int(time.time() * 1000000)),
                    "date_modified": str(int(time.time() * 1000000)),
                    "guid": "00000000-0000-4000-8000-000000000003",
                    "id": "3",
                    "name": "移动设备书签",
                    "type": "folder"
                }
            },
            "version": 1
        }
        
        id_counter = [4]  # 使用列表以便在嵌套函数中修改
        
        def create_folder(name: str, parent_children: List):
            """创建文件夹节点"""
            folder = {
                "children": [],
                "date_added": str(int(time.time() * 1000000)),
                "date_modified": str(int(time.time() * 1000000)),
                "guid": f"guid-{id_counter[0]}",
                "id": str(id_counter[0]),
                "name": name,
                "type": "folder"
            }
            id_counter[0] += 1
            parent_children.append(folder)
            return folder
        
        def create_bookmark(bm: Dict, parent_children: List):
            """创建书签节点"""
            bookmark = {
                "date_added": bm.get('add_date', str(int(time.time() * 1000000))),
                "guid": bm.get('guid', f"guid-{id_counter[0]}"),
                "id": str(id_counter[0]),
                "name": bm['name'],
                "type": "url",
                "url": bm['url']
            }
            id_counter[0] += 1
            parent_children.append(bookmark)
        
        # 组织书签到bookmark_bar
        bookmark_bar = chrome_data['roots']['bookmark_bar']
        
        for category, data in sorted(category_structure.items()):
            bookmarks = data['bookmarks']
            if not bookmarks:
                continue
            
            # 处理多级分类
            parts = category.split('/')
            current_parent = bookmark_bar['children']
            
            # 创建文件夹层次
            for part in parts:
                # 查找是否已存在该文件夹
                existing = None
                for child in current_parent:
                    if child.get('type') == 'folder' and child.get('name') == part:
                        existing = child
                        break
                
                if existing:
                    current_parent = existing['children']
                else:
                    folder = create_folder(part, current_parent)
                    current_parent = folder['children']
            
            # 添加书签
            for bm in bookmarks:
                create_bookmark(bm, current_parent)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(chrome_data, f, ensure_ascii=False, indent=3)
        
        print(f"\n✅ Chrome JSON书签文件已生成: {output_path}")
        print(f"   可替换Chrome书签文件（位置：Chrome用户数据目录/Default/Bookmarks）")
