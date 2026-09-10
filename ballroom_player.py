import os
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from prefix_audio import ( PrefixAudioManager, extract_dance_name, BGM_TOTAL_DURATION, DANCE_PATTERNS, DANCE_TYPES, DANCE_VOICE_MAP,
                                REVERSE_DANCE_MAP, EDGE_VOICES, POSITION_OPTIONS, ENGINE_OPTIONS, DEFAULT_CONFIG )
from vu_meter import VUMeter
from player import MusicPlayerCore
from collections import Counter, OrderedDict
import datetime
import json
import threading
import time
import random
from pathlib import Path
import pygame
import mutagen
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.wave import WAVE
from mutagen.oggvorbis import OggVorbis
from mutagen.mp4 import MP4
import librosa
import numpy as np
import soundfile as sf
import tempfile
import hashlib
import warnings
warnings.filterwarnings("ignore", message=".*avx2 capable.*")


# ==================== 舞种顺序歌单生成器 ====================

class DanceOrderPlaylistGenerator:
    """舞种顺序歌单生成器 - 按舞种顺序从歌库生成播放列表"""
    
    def __init__(self, parent):
        self.parent = parent
        self.player = parent.player
        self.playlist_manager = parent.playlist_manager
        self.prefix_manager = parent.prefix_manager
        self.song_configs = parent.song_configs
        
        # 缓存
        self.library_cache = {}  # {dance_name: [file_paths]}
        self.library_index_file = "library_cache.json"
        self.last_library_paths = []  # 记忆上次歌库路径
        
        # 模板存储
        self.templates_file = "dance_templates.json"
        self.templates = self._load_templates()
        
        # 生成历史
        self.history_file = "generation_history.json"
        self.history = self._load_history()
        
        # 当前生成的元数据
        self.current_metadata = {}
        
        # 加载歌库缓存
        self._load_library_cache()



    # ==================== 舞种解析 ====================

    def _get_display_name(self, dance_name):
        """将输入的舞种名称映射到显示名称"""
        # 构建映射字典
        dance_map = {}
        for keyword, display in DANCE_PATTERNS:
            dance_map[keyword] = display
            dance_map[display] = display
        return dance_map.get(dance_name, dance_name)
    
    def parse_dance_order(self, text):
        """
        解析用户输入的舞种顺序文本
        支持多种格式：
        - 纯文本列：慢三\\n维也纳华尔兹\\n慢四
        - 带序号：1，慢三，2，慢四，3，探戈
        - 分隔符：慢三-慢四-探戈 或 慢三,慢四,探戈
        - 混合格式自动识别
        """
        if not text or not text.strip():
            return []
        
        raw = text.strip()
        
        # 第一步：按行分割
        lines = [l.strip() for l in raw.split('\n') if l.strip()]
        
        # 如果只有一行，尝试按分隔符分割
        if len(lines) == 1:
            # 尝试多种分隔符
            for sep in ['，', ',', '、', '，', ';', '；', '·', '、', ' ']:
                if sep in lines[0]:
                    parts = [p.strip() for p in lines[0].split(sep) if p.strip()]
                    if len(parts) > 1:
                        lines = parts
                    break
        
        # 第二步：清洗每个条目，去除序号
        dance_names = []
        for item in lines:
            # 去除序号模式：1. 1、1， (1) 1) 等
            cleaned = re.sub(r'^[\d]+[\.、，,）\)]\s*', '', item)
            cleaned = re.sub(r'^[（\(]\s*[\d]+\s*[）\)]\s*', '', cleaned)
            cleaned = cleaned.strip()
            if cleaned:
                dance_names.append(cleaned)
        
        return dance_names
    
    def get_dance_order_with_count(self, dance_names):
        """
        获取舞种顺序及每个舞种的出现次数
        返回：[(dance_name, count), ...] 按原始顺序
        """
        # 使用OrderedDict保持顺序，统计出现次数
        order_counter = OrderedDict()
        for dance in dance_names:
            if dance in order_counter:
                order_counter[dance] += 1
            else:
                order_counter[dance] = 1
        
        return list(order_counter.items())

    # ==================== 预览并扫描 ====================

    def preview_library_dances(self, folders):
        """
        预览文件夹中所有音乐文件的舞种识别结果
        
        Args:
            folders: 文件夹路径列表
        
        Returns:
            dict: {file_path: dance_name} 映射，包含用户修正后的结果
        """
        if not folders:
            return {}
        
        # ✅ 构建映射：匹配词 → 显示名称
        display_map = {}
        for keyword, display in DANCE_PATTERNS:
            display_map[keyword] = display
            display_map[display] = display
        
        music_extensions = {'.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg'}
        file_dance_map = {}  # {file_path: dance_name}
        
        # 扫描文件
        for folder in folders:
            if not os.path.exists(folder):
                continue
            for root, dirs, files in os.walk(folder):
                for file in files:
                    ext = os.path.splitext(file)[1].lower()
                    if ext in music_extensions:
                        file_path = os.path.join(root, file)
                        dance = self.prefix_manager.get_dance_name(file)
                        dance_name = display_map.get(dance, dance)  # ✅ 映射到显示名称
                        file_dance_map[file_path] = dance_name or "舞曲"
        
        return file_dance_map

    def show_library_preview(self, folders, callback):
        """
        显示歌库舞种预览窗口 - 确认后保存修改并加载歌库
        
        Args:
            folders: 文件夹路径列表
            callback: 确认后的回调函数，接收修正后的 dance_map
        """
        if not folders:
            messagebox.showwarning("提示", "请先选择歌库文件夹")
            return
        
        # 扫描文件
        self.parent.status_label.config(text="正在扫描文件...")
        self.parent.root.update()
        
        file_dance_map = self.preview_library_dances(folders)
        
        if not file_dance_map:
            messagebox.showinfo("提示", "未找到音乐文件")
            return
        
        self.parent.status_label.config(text=f"扫描完成，共 {len(file_dance_map)} 个文件")
        
        # 创建预览窗口
        preview_window = tk.Toplevel(self.parent.root)
        preview_window.title("歌库舞种预览")
        preview_window.geometry("800x700")
        preview_window.transient(self.parent.root)
        preview_window.grab_set()   # 阻止操作主窗口
        preview_window.focus_force()  # 强制获取焦点
        preview_window.configure(bg='#1a1a2e')
        
        # 标题
        tk.Label(preview_window, text="📁 歌库舞种预览",
                font=('微软雅黑', 14, 'bold'),
                bg='#1a1a2e', fg='#3498db').pack(pady=10)
                
        total_files = len(file_dance_map)
        recognized = sum(1 for d in file_dance_map.values() if d != "（舞曲）")
        
        stats_label = tk.Label(preview_window,
                            text=f"总文件: {total_files}  |  已识别: {recognized}  |  未识别: {total_files - recognized}",
                            bg='#1a1a2e', fg='#ecf0f1', font=('微软雅黑', 10))
        stats_label.pack(pady=5)
        
        # 表格
        table_frame = tk.Frame(preview_window, bg='#1a1a2e')
        table_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        columns = ('文件名', '识别舞种', '状态')
        tree = ttk.Treeview(table_frame, columns=columns, show='headings', height=15)
        
        tree.heading('文件名', text='文件名')
        tree.heading('识别舞种', text='识别舞种')
        tree.heading('状态', text='状态')
        
        tree.column('文件名', width=400, anchor='w')
        tree.column('识别舞种', width=150, anchor='center')
        tree.column('状态', width=80, anchor='center')
        
        vscroll = ttk.Scrollbar(table_frame, orient='vertical', command=tree.yview)
        hscroll = ttk.Scrollbar(table_frame, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
        
        tree.grid(row=0, column=0, sticky='nsew')
        vscroll.grid(row=0, column=1, sticky='ns')
        hscroll.grid(row=1, column=0, sticky='ew')
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        
        # 存储修正后的映射
        modified_map = file_dance_map.copy()
        
        # 填充数据
        for file_path, dance in file_dance_map.items():
            filename = os.path.basename(file_path)
            status = "✅" if dance != "（舞曲）" else "❌"
            tree.insert('', 'end', values=(filename, dance, status), tags=(file_path,))
        
        # 右键菜单 - 修正舞种
        def show_correct_menu(event):
            item = tree.identify_row(event.y)
            if not item:
                return
            tree.selection_set(item)
            
            values = tree.item(item, 'values')
            current_dance = values[1]
            file_path = tree.item(item, 'tags')[0]
            
            menu = tk.Menu(preview_window, tearoff=0)
            
            dance_list = DANCE_TYPES
            for dance in dance_list:
                menu.add_command(label=dance,
                            command=lambda d=dance, fp=file_path, item_id=item:
                            update_dance(fp, d, item_id))
            
            menu.post(event.x_root, event.y_root)
        
        def update_dance(file_path, new_dance, item_id):
            """更新舞种"""
            modified_map[file_path] = new_dance
            values = list(tree.item(item_id, 'values'))
            values[1] = new_dance
            values[2] = "✅" if new_dance != "（舞曲）" else "❌"
            tree.item(item_id, values=values)
            
            # 更新统计
            total = len(modified_map)
            recognized = sum(1 for d in modified_map.values() if d != "（舞曲）")
            stats_label.config(text=f"总文件: {total}  |  已识别: {recognized}  |  未识别: {total - recognized}")
        
        tree.bind('<Button-3>', show_correct_menu)
        
        # 底部按钮
        btn_frame = tk.Frame(preview_window, bg='#1a1a2e')
        btn_frame.pack(pady=15)
        
        def on_confirm():
            """确认使用：保存修正 + 加载歌库"""
            # 先关闭预览窗口
            preview_window.destroy()
            # 然后执行加载（通过 callback）
            callback(modified_map)
        
        def on_cancel():
            preview_window.destroy()
        
        tk.Button(btn_frame, text="✅ 确认使用", command=on_confirm,
                bg='#2ecc71', fg='white', font=('微软雅黑', 10, 'bold'),
                width=12, cursor='hand2').pack(side=tk.LEFT, padx=10)
        
        tk.Button(btn_frame, text="❌ 取消", command=on_cancel,
                bg='#e74c3c', fg='white', width=10, cursor='hand2').pack(side=tk.LEFT, padx=10)
        
        tk.Label(preview_window, text="💡 右键点击舞种名称可手动修正",
                bg='#1a1a2e', fg='#7f8c8d', font=('微软雅黑', 9)).pack(pady=5)

    # ==================== 歌库扫描与缓存 ====================
    
    def scan_library(self, folders):
        """
        扫描一个或多个文件夹，建立舞种索引
        返回：{dance_name: [file_paths]}
        """
        if not folders:
            return {}
        
        music_extensions = {'.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.m4a'}
        library = {}
        total_files = 0
        
        # 显示进度
        self.parent.status_label.config(text="正在扫描歌库...")
        self.parent.root.update()
        
        for folder in folders:
            if not os.path.exists(folder):
                continue
            for root, dirs, files in os.walk(folder):
                for file in files:
                    ext = os.path.splitext(file)[1].lower()
                    if ext in music_extensions:
                        file_path = os.path.join(root, file)
                        total_files += 1
                        
                        # 使用prefix_manager的舞种识别（含手动映射）
                        dance_name = self.prefix_manager.get_dance_name(file)
                        
                        if dance_name:
                            if dance_name not in library:
                                library[dance_name] = []
                            library[dance_name].append(file_path)
                        
                        # 每100个文件更新一次状态
                        if total_files % 100 == 0:
                            self.parent.status_label.config(
                                text=f"扫描中... {total_files} 个文件"
                            )
                            self.parent.root.update()
        
        # 去重（按路径）
        for dance in library:
            library[dance] = list(set(library[dance]))
        
        self.parent.status_label.config(text=f"扫描完成，共 {total_files} 个文件，{len(library)} 种舞种")
        
        return library
    
    def refresh_library_cache(self, folders):
        """刷新歌库缓存"""
        if not folders:
            messagebox.showwarning("提示", "请先选择歌库文件夹")
            return None
        
        library = self.scan_library(folders)
        if library:
            self.library_cache = library
            self.last_library_paths = folders
            self._save_library_cache()
            return library
        return None
    
    def _load_library_cache(self):
        """加载歌库缓存"""
        try:
            if os.path.exists(self.library_index_file):
                with open(self.library_index_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.library_cache = data.get('library', {})
                    self.last_library_paths = data.get('paths', [])
        except Exception as e:
            print(f"加载歌库缓存失败: {e}")
            self.library_cache = {}
            self.last_library_paths = []
    
    def _save_library_cache(self):
        """保存歌库缓存"""
        try:
            data = {
                'library': self.library_cache,
                'paths': self.last_library_paths,
                'updated': datetime.datetime.now().isoformat()
            }
            with open(self.library_index_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存歌库缓存失败: {e}")
    
    # ==================== 核心生成逻辑 ====================
    
    def generate_playlist(self, dance_order, library, remark=""):
        """
        根据舞种顺序和歌库生成播放列表
        
        # Args:
        #     dance_order: 舞种顺序列表（含重复）
        #     library: 歌库索引 {dance: [file_paths]}
        #     remark: 用户备注
        
        # Returns:
        #     (playlist, metadata, warnings)
        """
        if not dance_order:
            return [], {}, ["舞种顺序为空"]
        
        if not library:
            return [], {}, ["歌库为空"]
        
        # 统计舞种出现次数
        order_counter = OrderedDict()
        for dance in dance_order:
            order_counter[dance] = order_counter.get(dance, 0) + 1
        
        # 第一步：为每个舞种预先选好歌曲列表
        dance_song_pools = {}
        preview_data = []
        warnings = []
        # selected_songs = []
        
        for dance, needed_count in order_counter.items():
            # ✅ 将输入名称映射到显示名称
            actual_dance = self._get_display_name(dance)
            available = library.get(actual_dance, [])
            available_count = len(available)
            
            # 确定选取数量
            if available_count == 0:
                selected = []
                status = "❌ 无歌曲"
                warnings.append(f"⚠️ 跳过: {dance} (歌库中无此舞种)")
            elif available_count >= needed_count:
                selected = random.sample(available, needed_count)
                status = f"✅ 充足 ({available_count}首)"
            else:
                # 不足，允许重复使用
                selected = []
                while len(selected) < needed_count:
                    remaining = needed_count - len(selected)
                    sample_size = min(available_count, remaining)
                    selected.extend(random.sample(available, sample_size))
                status = f"⚠️ 不足 ({available_count}首，将重复使用)"
                warnings.append(f"⚠️ {dance}: 需要 {needed_count} 首，歌库只有 {available_count} 首，将重复使用")
            
            dance_song_pools[dance] = selected
            preview_data.append({
                'dance': dance,
                'needed': needed_count,
                'available': available_count,
                'selected': len(selected),
                'status': status,
                'songs': selected
            })
        
        # 第二步：交叉排列 - 按舞种顺序轮流取歌
        selected_songs = []
        max_count = max([len(pool) for pool in dance_song_pools.values()]) if dance_song_pools else 0
        
        for i in range(max_count):
            for dance in order_counter.keys():
                pool = dance_song_pools.get(dance, [])
                if i < len(pool):
                    selected_songs.append(pool[i])
        
        # 生成元数据
        metadata = {
            'generated_time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'dance_order': dance_order.copy(),
            'dance_count': len(order_counter),
            'total_songs': len(selected_songs),
            'remark': remark,
            'library_paths': self.last_library_paths.copy(),
            'preview_data': preview_data,
            'warnings': warnings
        }
        
        self.current_metadata = metadata
        
        return selected_songs, metadata, warnings
    
    # ==================== 预览功能 ====================
    
    def show_preview(self, dance_order, library, callback):
        """
        显示预览窗口
        
        Args:
            dance_order: 舞种顺序列表
            library: 歌库索引
            callback: 确认生成的回调函数
        """
        if not dance_order:
            messagebox.showwarning("提示", "舞种顺序为空，请先输入")
            return
        
        if not library:
            messagebox.showwarning("提示", "歌库为空，请先扫描")
            return
        
        # 统计
        order_counter = OrderedDict()
        for dance in dance_order:
            order_counter[dance] = order_counter.get(dance, 0) + 1
        
        # 创建预览窗口
        preview_window = tk.Toplevel(self.parent.root)
        preview_window.title("预览 - 舞种顺序歌单生成")
        preview_window.geometry("750x666")
        preview_window.transient(self.parent.root)
        preview_window.grab_set()
        preview_window.configure(bg='#1a1a2e')
        
        # 标题
        tk.Label(preview_window, text="📋 舞种顺序预览",
                font=('微软雅黑', 14, 'bold'),
                bg='#1a1a2e', fg='#3498db').pack(pady=10)
        
        # 统计摘要
        total_needed = sum(order_counter.values())
        total_available = sum(len(library.get(d, [])) for d in order_counter.keys())
        
        summary_frame = tk.Frame(preview_window, bg='#1a1a2e')
        summary_frame.pack(fill=tk.X, padx=20, pady=5)
        
        tk.Label(summary_frame, text=f"舞种数: {len(order_counter)}  |  所需歌曲: {total_needed} 首  |  歌库歌曲: {total_available} 首",
                bg='#1a1a2e', fg='#ecf0f1', font=('微软雅黑', 10)).pack(side=tk.LEFT)
        
        # 表格（带滚动条）
        table_frame = tk.Frame(preview_window, bg='#1a1a2e')
        table_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # 创建Treeview
        columns = ('序号', '舞种', '出现次数', '歌库数量', '将选数量', '状态')
        tree = ttk.Treeview(table_frame, columns=columns, show='headings', height=12)
        
        col_widths = {'序号': 40, '舞种': 100, '出现次数': 70, '歌库数量': 70, '将选数量': 70, '状态': 100}
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=col_widths.get(col, 80), anchor='center')
        
        # 滚动条
        vscroll = ttk.Scrollbar(table_frame, orient='vertical', command=tree.yview)
        hscroll = ttk.Scrollbar(table_frame, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
        
        tree.grid(row=0, column=0, sticky='nsew')
        vscroll.grid(row=0, column=1, sticky='ns')
        hscroll.grid(row=1, column=0, sticky='ew')
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        
        # 填充数据
        status_colors = {
            '✅': '#2ecc71',
            '⚠️': '#f39c12',
            '❌': '#e74c3c'
        }
        
        for idx, (dance, needed) in enumerate(order_counter.items(), 1):
            available = len(library.get(dance, []))
            if available == 0:
                selected = 0
                status = "❌ 无歌曲"
                color = status_colors['❌']
            elif available >= needed:
                selected = needed
                status = "✅ 充足"
                color = status_colors['✅']
            else:
                selected = needed
                status = f"⚠️ 不足({available}首将重复)"
                color = status_colors['⚠️']
            
            tree.insert('', 'end', values=(idx, dance, needed, available, selected, status), tags=(color,))
        
        # 颜色标签
        tree.tag_configure('#2ecc71', foreground='#2ecc71')
        tree.tag_configure('#f39c12', foreground='#f39c12')
        tree.tag_configure('#e74c3c', foreground='#e74c3c')

        # 播放列表名称输入
        name_frame = tk.Frame(preview_window, bg='#1a1a2e')
        name_frame.pack(fill=tk.X, padx=20, pady=10)
        
        tk.Label(name_frame, text="列表名称:", bg='#1a1a2e', fg='#ecf0f1',
                font=('微软雅黑', 10)).pack(side=tk.LEFT)
        
        name_entry = tk.Entry(name_frame, width=20, font=('微软雅黑', 10))
        name_entry.pack(side=tk.LEFT, padx=10)
        # 默认填入时间+舞种信息
        default_name = f"{datetime.datetime.now().strftime('%m%d_%H%M')}"
        name_entry.insert(0, default_name)
            
        # 备注输入
        remark_frame = tk.Frame(preview_window, bg='#1a1a2e')
        remark_frame.pack(fill=tk.X, padx=20, pady=10)
        
        tk.Label(remark_frame, text="备注信息:", bg='#1a1a2e', fg='#ecf0f1',
                font=('微软雅黑', 10)).pack(side=tk.LEFT)
        
        remark_entry = tk.Entry(remark_frame, width=80, font=('微软雅黑', 10))
        remark_entry.pack(side=tk.LEFT, padx=10)
        
        # 底部按钮
        button_frame = tk.Frame(preview_window, bg='#1a1a2e')
        button_frame.pack(pady=15)
        
        def on_generate():
            playlist_name = name_entry.get().strip()
            if not playlist_name:
                messagebox.showwarning("提示", "请先输入播放列表名称")
                return
            remark = remark_entry.get().strip()
            callback(playlist_name, remark)
            preview_window.destroy()
        
        # 更新按钮文字
        tk.Button(button_frame, text="✅ 开始生成播放列表",
                 command=on_generate,
                 bg='#2ecc71', fg='white', font=('微软雅黑', 10, 'bold'),
                 width=15, cursor='hand2').pack(side=tk.LEFT, padx=10)
        
        tk.Button(button_frame, text="取消",
                 command=preview_window.destroy,
                 bg='#95a5a6', fg='white', font=('微软雅黑', 10),
                 width=10, cursor='hand2').pack(side=tk.LEFT, padx=10)
    
    # ==================== 模板管理 ====================
    
    def _load_templates(self):
        """加载模板"""
        try:
            if os.path.exists(self.templates_file):
                with open(self.templates_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载模板失败: {e}")
        return {}
    
    def _save_templates(self):
        """保存模板"""
        try:
            with open(self.templates_file, 'w', encoding='utf-8') as f:
                json.dump(self.templates, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存模板失败: {e}")
    
    def save_template(self, name, dance_order):
        """保存舞种顺序模板"""
        if not name or not dance_order:
            return False
        
        self.templates[name] = {
            'name': name,
            'dance_order': dance_order,
            'created': datetime.datetime.now().isoformat(),
            'count': len(dance_order),
            'unique_dances': len(set(dance_order))
        }
        self._save_templates()
        return True
    
    def load_template(self, name):
        """加载模板"""
        return self.templates.get(name, {}).get('dance_order', [])

    def load_template_to_editor(self, dance_order, template_name):
        """将模板加载到舞种顺序文本框中"""
        if hasattr(self, 'dance_order_text'):
            self.dance_order_text.delete('1.0', tk.END)
            self.dance_order_text.insert('1.0', '\n'.join(dance_order))
            self.status_label.config(text=f"已加载模板: {template_name}")
        else:
            print("错误: dance_order_text 控件不存在")

    def delete_template(self, name):
        """删除模板"""
        if name in self.templates:
            del self.templates[name]
            self._save_templates()
            return True
        return False
    
    def get_template_names(self):
        """获取所有模板名称"""
        return list(self.templates.keys())
    
    def show_template_manager(self):
        """显示模板管理窗口"""
        manager_window = tk.Toplevel(self.parent.root)
        manager_window.title("模板管理")
        manager_window.geometry("600x600")
        manager_window.transient(self.parent.root)
        manager_window.grab_set()
        manager_window.configure(bg='#1a1a2e')
        
        tk.Label(manager_window, text="📁 舞种顺序模板管理",
                font=('微软雅黑', 14, 'bold'),
                bg='#1a1a2e', fg='#3498db').pack(pady=10)
        
        # 模板列表
        list_frame = tk.Frame(manager_window, bg='#1a1a2e')
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Treeview
        columns = ('名称', '舞种数', '独立舞种数', '创建时间')
        tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=12)
        
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=80, anchor='center')
        tree.column('名称', width=120)
        tree.column('创建时间', width=150)
        
        vscroll = ttk.Scrollbar(list_frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=vscroll.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vscroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 填充模板列表
        for name, data in self.templates.items():
            tree.insert('', 'end', values=(
                name,
                data.get('count', 0),
                data.get('unique_dances', 0),
                data.get('created', '')[:16]
            ))
        
        # 操作按钮
        btn_frame = tk.Frame(manager_window, bg='#1a1a2e')
        btn_frame.pack(pady=15)
        
        def on_load():
            selection = tree.selection()
            if not selection:
                messagebox.showinfo("提示", "请先选择一个模板")
                return
            item = tree.item(selection[0])
            name = item['values'][0]
            dance_order = self.load_template(name)
            if dance_order:
                # 返回到主窗口并填充
                manager_window.destroy()
                # self.dance_order_text.delete('1.0', tk.END)
                # self.dance_order_text.insert('1.0', '\n'.join(dance_order))
                # self.status_label.config(text=f"已加载模板: {name}")
                # # 自动解析
                # self.generator.parse_dance_order('\n'.join(dance_order))

                # 通过父窗口的方法来填充文本框
                self.parent.load_template_to_editor(dance_order, name)

        def on_delete():
            selection = tree.selection()
            if not selection:
                messagebox.showinfo("提示", "请先选择一个模板")
                return
            item = tree.item(selection[0])
            name = item['values'][0]
            if messagebox.askyesno("确认删除", f"确定要删除模板 '{name}' 吗？"):
                if self.delete_template(name):
                    tree.delete(selection[0])
                    self.parent.status_label.config(text=f"已删除模板: {name}")
        
        def on_edit():
            selection = tree.selection()
            if not selection:
                messagebox.showinfo("提示", "请先选择一个模板")
                return
            item = tree.item(selection[0])
            name = item['values'][0]
            dance_order = self.load_template(name)
            if dance_order:
                manager_window.destroy()
                # 打开编辑对话框
                self.show_template_edit_dialog(name, dance_order)
        
        tk.Button(btn_frame, text="加载", command=on_load,
                 bg='#3498db', fg='white', width=10, cursor='hand2').pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="编辑", command=on_edit,
                 bg='#f39c12', fg='white', width=10, cursor='hand2').pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="删除", command=on_delete,
                 bg='#e74c3c', fg='white', width=10, cursor='hand2').pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="关闭", command=manager_window.destroy,
                 bg='#95a5a6', fg='white', width=10, cursor='hand2').pack(side=tk.LEFT, padx=5)
    
    def show_template_edit_dialog(self, name, dance_order):
        """编辑模板对话框"""
        edit_window = tk.Toplevel(self.parent.root)
        edit_window.title(f"编辑模板 - {name}")
        edit_window.geometry("500x400")
        edit_window.transient(self.parent.root)
        edit_window.grab_set()
        edit_window.configure(bg='#1a1a2e')
        
        tk.Label(edit_window, text=f"编辑模板: {name}",
                font=('微软雅黑', 14, 'bold'),
                bg='#1a1a2e', fg='#3498db').pack(pady=10)
        
        tk.Label(edit_window, text="舞种顺序（每行一个）:",
                bg='#1a1a2e', fg='#ecf0f1', font=('微软雅黑', 10)).pack(anchor='w', padx=20)
        
        text_frame = tk.Frame(edit_window, bg='#1a1a2e')
        text_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        text_widget = tk.Text(text_frame, font=('微软雅黑', 10), bg='#2a2a4e',
                            fg='#ecf0f1', insertbackground='white')
        text_widget.pack(fill=tk.BOTH, expand=True)
        text_widget.insert('1.0', '\n'.join(dance_order))
        
        btn_frame = tk.Frame(edit_window, bg='#1a1a2e')
        btn_frame.pack(pady=15)
        
        def on_save():
            new_order = text_widget.get('1.0', tk.END).strip().split('\n')
            new_order = [d.strip() for d in new_order if d.strip()]
            if not new_order:
                messagebox.showwarning("提示", "舞种顺序不能为空")
                return
            
            # 更新模板
            self.templates[name]['dance_order'] = new_order
            self.templates[name]['count'] = len(new_order)
            self.templates[name]['unique_dances'] = len(set(new_order))
            self.templates[name]['updated'] = datetime.datetime.now().isoformat()
            self._save_templates()
            
            edit_window.destroy()
            self.parent.status_label.config(text=f"模板已更新: {name}")
        
        tk.Button(btn_frame, text="保存", command=on_save,
                 bg='#2ecc71', fg='white', width=10, cursor='hand2').pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="取消", command=edit_window.destroy,
                 bg='#95a5a6', fg='white', width=10, cursor='hand2').pack(side=tk.LEFT, padx=5)
    
    # ==================== 生成历史 ====================
    
    def _load_history(self):
        """加载生成历史"""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载历史失败: {e}")
        return []
    
    def _save_history(self):
        """保存生成历史"""
        try:
            # 只保留最近100条
            if len(self.history) > 100:
                self.history = self.history[-100:]
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存历史失败: {e}")
    
    def add_history(self, metadata):
        """添加一条生成记录"""
        record = {
            'time': metadata.get('generated_time', datetime.datetime.now().isoformat()),
            'dance_count': metadata.get('dance_count', 0),
            'total_songs': metadata.get('total_songs', 0),
            'remark': metadata.get('remark', ''),
            'dance_order_preview': metadata.get('dance_order', [])[:10],
            'library_paths': metadata.get('library_paths', [])
        }
        self.history.append(record)
        self._save_history()
    
    def show_history(self):
        """显示生成历史"""
        if not self.history:
            messagebox.showinfo("提示", "暂无生成记录")
            return
        
        history_window = tk.Toplevel(self.parent.root)
        history_window.title("生成历史")
        history_window.geometry("700x400")
        history_window.transient(self.parent.root)
        history_window.grab_set()
        history_window.configure(bg='#1a1a2e')
        
        tk.Label(history_window, text="📜 生成历史记录",
                font=('微软雅黑', 14, 'bold'),
                bg='#1a1a2e', fg='#3498db').pack(pady=10)
        
        # 表格
        frame = tk.Frame(history_window, bg='#1a1a2e')
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        columns = ('时间', '舞种数', '歌曲数', '备注')
        tree = ttk.Treeview(frame, columns=columns, show='headings', height=12)
        
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=80, anchor='center')
        tree.column('时间', width=150)
        tree.column('备注', width=200)
        
        vscroll = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=vscroll.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vscroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        for record in reversed(self.history):
            tree.insert('', 'end', values=(
                record.get('time', '')[:16],
                record.get('dance_count', 0),
                record.get('total_songs', 0),
                record.get('remark', '')[:20]
            ))
        
        tk.Button(history_window, text="关闭",
                 command=history_window.destroy,
                 bg='#95a5a6', fg='white', width=10, cursor='hand2').pack(pady=15)
    
    # ==================== 导出功能 ====================
    
    def export_playlist(self, playlist, metadata, format_type):
        """
        导出播放列表
        
        Args:
            playlist: 歌曲路径列表
            metadata: 元数据
            format_type: 'm3u', 'txt', 'excel'
        """
        if not playlist:
            messagebox.showwarning("提示", "播放列表为空，无法导出")
            return
        
        # 生成默认文件名
        default_name = f"playlist_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        if format_type == 'm3u':
            file_path = filedialog.asksaveasfilename(
                defaultextension=".m3u",
                filetypes=[("M3U播放列表", "*.m3u"), ("所有文件", "*.*")],
                initialfile=f"{default_name}.m3u"
            )
            if not file_path:
                return
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("#EXTM3U\n")
                f.write(f"# 生成时间: {metadata.get('generated_time', '')}\n")
                f.write(f"# 舞种数: {metadata.get('dance_count', 0)}\n")
                f.write(f"# 歌曲数: {len(playlist)}\n")
                if metadata.get('remark'):
                    f.write(f"# 备注: {metadata['remark']}\n")
                f.write("\n")
                
                for song in playlist:
                    f.write(f"{song}\n")
            
            messagebox.showinfo("导出成功", f"已导出 M3U 文件:\n{file_path}")
            
        elif format_type == 'txt':
            file_path = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
                initialfile=f"{default_name}.txt"
            )
            if not file_path:
                return
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(f"播放列表导出\n")
                f.write(f"{'='*50}\n")
                f.write(f"生成时间: {metadata.get('generated_time', '')}\n")
                f.write(f"舞种数: {metadata.get('dance_count', 0)}\n")
                f.write(f"歌曲数: {len(playlist)}\n")
                if metadata.get('remark'):
                    f.write(f"备注: {metadata['remark']}\n")
                f.write(f"{'='*50}\n\n")
                
                for idx, song in enumerate(playlist, 1):
                    f.write(f"{idx}. {os.path.basename(song)}\n")
                    f.write(f"   {song}\n\n")
            
            messagebox.showinfo("导出成功", f"已导出文本文件:\n{file_path}")
            
        elif format_type == 'excel':
            try:
                import openpyxl
                from openpyxl.styles import Font, Alignment
            except ImportError:
                messagebox.showerror("错误", "未安装 openpyxl 库\n请运行: pip install openpyxl")
                return
            
            file_path = filedialog.asksaveasfilename(
                defaultextension=".xlsx",
                filetypes=[("Excel文件", "*.xlsx"), ("所有文件", "*.*")],
                initialfile=f"{default_name}.xlsx"
            )
            if not file_path:
                return
            
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "播放列表"
            
            # 标题
            ws['A1'] = "舞种顺序播放列表"
            ws['A1'].font = Font(size=14, bold=True)
            ws.merge_cells('A1:E1')
            
            # 元数据
            row = 3
            ws[f'A{row}'] = f"生成时间: {metadata.get('generated_time', '')}"
            row += 1
            ws[f'A{row}'] = f"舞种数: {metadata.get('dance_count', 0)}"
            row += 1
            ws[f'A{row}'] = f"歌曲数: {len(playlist)}"
            row += 1
            if metadata.get('remark'):
                ws[f'A{row}'] = f"备注: {metadata['remark']}"
                row += 1
            row += 1
            
            # 表头
            headers = ['序号', '歌名', '文件路径', '舞种']
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=row, column=col, value=header)
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal='center')
            row += 1
            
            # 数据
            for idx, song in enumerate(playlist, 1):
                filename = os.path.basename(song)
                dance = self.prefix_manager.get_dance_name(filename)
                ws.cell(row=row, column=1, value=idx)
                ws.cell(row=row, column=2, value=filename)
                ws.cell(row=row, column=3, value=song)
                ws.cell(row=row, column=4, value=dance or '未知')
                row += 1
            
            # 调整列宽
            ws.column_dimensions['A'].width = 8
            ws.column_dimensions['B'].width = 30
            ws.column_dimensions['C'].width = 50
            ws.column_dimensions['D'].width = 15
            
            wb.save(file_path)
            messagebox.showinfo("导出成功", f"已导出 Excel 文件:\n{file_path}")



class PlaylistManager:
    """播放列表管理类"""
    def __init__(self, parent):
        self.parent = parent
        self.playlists = {
            1: {"name": "临时列表", "songs": [], "file": None, "remark": ""},
        }
        self.current_playlist = 1
        self.config_file = "playlists_config.json"
        self.load_playlists()
    
    def load_playlists(self):
        """加载播放列表配置"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for key, value in data.items():
                        if int(key) in self.playlists:
                            self.playlists[int(key)].update(value)
                        else:
                            # 确保 remark 字段存在
                            if "remark" not in value:
                                value["remark"] = ""
                            self.playlists[int(key)] = value
        except Exception as e:
            print(f"加载播放列表失败: {e}")
    
    def save_playlists(self):
        """保存播放列表到配置文件"""
        try:
            data = {}
            for key, value in self.playlists.items():
                data[key] = {
                    "name": value["name"],
                    "songs": value["songs"],
                    "file": value["file"],
                    "remark": value.get("remark", "")
                }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存播放列表失败: {e}")
    
    def add_song(self, playlist_num, song_path):
        """添加歌曲到播放列表"""
        if playlist_num in self.playlists:
            if song_path not in self.playlists[playlist_num]["songs"]:
                self.playlists[playlist_num]["songs"].append(song_path)
                self.save_playlists()
                return True
        return False
    
    def remove_song(self, playlist_num, index):
        """从播放列表移除歌曲"""
        if playlist_num in self.playlists:
            songs = self.playlists[playlist_num]["songs"]
            if 0 <= index < len(songs):
                songs.pop(index)
                self.save_playlists()
                return True
        return False
    
    def move_song(self, playlist_num, from_index, to_index):
        """移动歌曲位置"""
        if playlist_num in self.playlists:
            songs = self.playlists[playlist_num]["songs"]
            if 0 <= from_index < len(songs) and 0 <= to_index < len(songs):
                song = songs.pop(from_index)
                songs.insert(to_index, song)
                self.save_playlists()
                return True
        return False
    
    def create_playlist(self, name):
        """创建新播放列表（插入到临时列表后面）"""
        new_id = max(self.playlists.keys()) + 1
        self.playlists[new_id] = {"name": name, "songs": [], "file": None, "remark": ""}
        
        # 重新排序：临时列表(1)在第一位，新列表在第二位
        sorted_ids = list(self.playlists.keys())
        
        # 确保临时列表(1)在第一位
        if 1 in sorted_ids:
            sorted_ids.remove(1)
            sorted_ids.insert(0, 1)
        
        # 确保新列表在第二位（紧挨着临时列表）
        if new_id in sorted_ids:
            sorted_ids.remove(new_id)
            sorted_ids.insert(1, new_id)
        
        # 重新构建有序字典
        new_playlists = {}
        for pid in sorted_ids:
            new_playlists[pid] = self.playlists[pid]
        self.playlists = new_playlists
        
        self.save_playlists()
        return new_id

    def rename_playlist(self, playlist_num, new_name):
        """重命名播放列表"""
        if playlist_num in self.playlists:
            self.playlists[playlist_num]["name"] = new_name
            self.save_playlists()
            return True
        return False
    
    def delete_playlist(self, playlist_num):
        """删除播放列表"""
        if playlist_num in self.playlists and playlist_num not in [1]:
            del self.playlists[playlist_num]
            self.save_playlists()
            return True
        return False


class DanceMusicPlayer:
    def __init__(self, root):
        super().__init__()

        self.root = root
        self.root.title("舞厅舞曲播放编排系统-魅影制作")
        self.root.geometry("1300x800-8-35")
        self.root.configure(bg='#1a1a2e')

        # 创建状态栏
        self.create_status_bar()

        # 初始化核心组件
        self.player = MusicPlayerCore()
        self.playlist_manager = PlaylistManager(self)
        
        # 歌曲配置存储
        self.song_configs = {}
        
        # 加载歌曲配置
        self.load_song_configs()

        # 添加缓存
        self._duration_cache = {}
        self._metadata_cache = {}
        self._config_cache = {}

        # BPM缓存
        self.bpm_cache = {}
        self.bpm_threads = {}
        
        # 默认设置
        self.default_settings = {
            'start_time': 0,
            'play_duration': 0,  # 0表示完整播放
            'pause_duration': 0,
            'volume': 80,
            'speed': 100,
            'pitch': 0,
            'fade_in_duration': 2,
            'fade_out_duration': 3
        }
        
        # 防止滑块事件循环的标志
        self._updating_sliders = False
        self._is_playing = False
        
        # ✅ 关键修复：提前初始化所有需要的属性
        self._is_playing_prefix = False
        self._fade_out_started = False
        self._is_transitioning = False    # 防止重复过渡
        self._pending_speed = None  # 待应用的速度
        self._pending_pitch = None  # 待应用的音调
        self._playback_completed = False  # ✅ 添加：播放完成标记
        
        # 前缀音相关属性
        self._prefix_delay_timer = None
        self._prefix_timer_id = None
        self._prefix_to_song_timer = None
        self._prefix_fade_out_timer = None

        self.prefix_enabled = False
        self.current_prefix_file = None
        self.prefix_manager = PrefixAudioManager()
        self._current_prefix_config_name = None  # 当前使用的前缀音配置名称

        # 加载前缀音配置
        self._prefix_config = {}
        self._load_prefix_config()

        # ✅ 在创建菜单后，更新关闭前缀音状态
        self.root.after(100, self._update_close_prefix_menu)

        # ✅ 保存"关闭前缀音"菜单项的引用
        self._close_prefix_menu_ref = None

        # ✅ 初始化前缀音状态显示（关闭状态）
        self._update_prefix_status_display()

        # 播放时间相关属性
        self._play_start_time = time.time()
        self._play_start_pos = 0
        self._last_logged_pos = -1

        # 播放列表标签拖放相关
        self._drag_playlist_start = None  # 拖放开始的播放列表ID
        self._drag_playlist_widget = None  # 被拖动的按钮
        self._drag_playlist_offset_x = 0  # 鼠标偏移X
        self._drag_playlist_offset_y = 0  # 鼠标偏移Y

        # 记录实际正在播放的播放列表ID
        self.playing_song_path = None
        self.playing_playlist_id = None  # 记录正在播放的列表ID
        self.playing_song_index = -1     # 记录正在播放的歌曲索引
        
        # 设置样式
        self.setup_styles()
        
        # 创建界面
        self.create_menu_bar()
        self.create_control_bar()
        self.create_main_content()
        
        # 初始化变量
        self.current_playlist = 1
        self.song_library_dir = None
        self.progress_dragging = False

        # 拖动排序相关变量
        self._drag_start_index = None  # 拖动开始的索引
        self._drag_target_index = None  # 拖动目标的索引
        self._drag_indicator = None  # 拖动指示线
        self._drag_canvas = None  # 拖动指示线的Canvas
        self._dragged_item = None  # 拖动的行

        # 拖放指示器
        self._drop_indicator_canvas = None
        self._drop_indicator_id = None
        self._drop_indicator_target = None

        # 延迟初始化的组件
        self._light_control_initialized = False
        self._cache_manager_initialized = False
        
        self.setup_shortcuts()
        self.setup_drag_drop()
        
        # 绑定窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # 启动进度更新线程
        self.update_progress_thread()
        
        # 启动VU表更新线程
        self.update_vu_meter_thread()

        try:
            from skin import apply_skin_to_player
            self.colors = apply_skin_to_player(self)
            # 强制刷新两次，确保所有组件重绘
            self.root.update()
            self.root.update_idletasks()
        except Exception as e:
            print(f"⚠️ 皮肤应用失败: {e}")

    def get_song_config_cached(self, song_path):
        """获取歌曲配置（带缓存）"""
        if song_path not in self._config_cache:
            self._config_cache[song_path] = self.song_configs.get(song_path, {})
        return self._config_cache[song_path]

    def clear_caches(self):
        """清理缓存"""
        self._duration_cache.clear()
        self._metadata_cache.clear()
        self._config_cache.clear()

    def analyze_bpm_async(self, song_path):
        """异步分析BPM"""
        if song_path in self.bpm_cache:
            return self.bpm_cache[song_path]
        
        # 检查是否已在分析中
        if song_path in self.bpm_threads:
            return None
        
        def analyze():
            try:
                # 分析BPM
                bpm = self.analyze_bpm(song_path)
                if bpm:
                    self.bpm_cache[song_path] = bpm
                    # 更新UI
                    self.root.after(0, self.update_bpm_display, song_path, bpm)
            except Exception as e:
                print(f"BPM分析失败: {e}")
            finally:
                # 清理线程记录
                if song_path in self.bpm_threads:
                    del self.bpm_threads[song_path]
        
        # 记录分析中的歌曲
        self.bpm_threads[song_path] = True
        
        # 启动后台分析
        threading.Thread(target=analyze, daemon=True).start()
        return None

    def get_current_song_path(self):
        """获取当前播放歌曲的路径"""
        songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
        if self.player.current_index >= 0 and self.player.current_index < len(songs):
            return songs[self.player.current_index]
        return None
    
    def save_song_configs_throttled(self):
        """节流保存歌曲配置"""
        if hasattr(self, '_save_timer'):
            self.root.after_cancel(self._save_timer)
    
        self._save_timer = self.root.after(1000, self.save_song_configs)
    
    def trigger_next_song(self):
        """触发下一首（播放完成后）"""
        print("🎯 播放完成，准备播放下一首")

        # ✅ 使用记录的播放列表ID（这是正在播放的列表）
        playlist_id = self.playing_playlist_id
        if playlist_id is None:
            # 如果没有正在播放的列表，才使用当前查看的列表
            playlist_id = self.current_playlist

        # 固定playlist_id，避免lambda闭包问题
        fixed_playlist_id = playlist_id

        # ✅ 获取停顿时长（滑音已经在播放时长内完成了）
        song_path = self.get_current_song_path()
        if song_path:
            config = self.song_configs.get(song_path, {})
            pause_duration = config.get('pause_duration', self.default_settings['pause_duration'])
            
            # ✅ 只等待停顿时长（滑音已经在播放时长内处理了）
            print(f"⏰ 停止 {pause_duration:.1f}s 后播放下一首")
            
            if pause_duration > 0:
                # 有停顿时长，等待后播放
                self.root.after(int(pause_duration * 1000), lambda: self._do_next_song(fixed_playlist_id))
            else:
                # ✅ 没有停顿时长，延迟300ms后播放下一首
                self.root.after(300, lambda: self._do_next_song(fixed_playlist_id))
        else:
            self.root.after(300, lambda: self._do_next_song(fixed_playlist_id))

    def _do_next_song(self, playlist_id=None):
        """实际执行下一首切换"""

        # 使用传入的列表ID，如果没有则使用播放记录
        if playlist_id is None:
            playlist_id = self.playing_playlist_id
        if playlist_id is None:
            playlist_id = self.current_playlist

        # ✅ 更新正在播放的列表ID
        self.playing_playlist_id = playlist_id  # 记录正在播放的列表

        self._playback_completed = False
        # ✅ 关键：在调用 next_song() 之前重置 _is_transitioning
        self._is_transitioning = False
        
        # ✅ 保存用户当前查看的列表ID（非播放列表）
        user_viewing_playlist = self.current_playlist
        
        # 调用 next_song
        self.next_song()
     
        # 延迟刷新UI
        if hasattr(self, '_ui_refresh_after_id'):
            self.root.after_cancel(self._ui_refresh_after_id)

        self._ui_refresh_after_id = self.root.after(200, self._refresh_ui_after_song_change)

    def _refresh_ui_after_song_change(self):
        """歌曲切换后刷新UI"""
        print("🔄 刷新UI（歌曲切换后）")
        
        # ✅ 刷新所有播放列表视图
        if hasattr(self, 'refresh_playlist_display'):
            self.refresh_playlist_display()
        
        # ✅ 刷新当前播放列表
        if hasattr(self, 'refresh_current_playlist'):
            self.refresh_current_playlist()
        
        # ✅ 刷新整个UI（如果存在这个方法）
        if hasattr(self, 'update_ui'):
            self.update_ui()
        
        # ✅ 强制刷新播放列表控件
        if hasattr(self, 'playlist_tree'):
            self.playlist_tree.update_idletasks()
            self.playlist_tree.update()
        
        # ✅ 如果有多个播放列表控件，全部刷新
        if hasattr(self, 'playlist_widgets'):
            for widget in self.playlist_widgets:
                if widget and widget.winfo_exists():
                    widget.update_idletasks()
                    widget.update()


    def load_song_configs(self):
        """加载歌曲配置"""
        try:
            config_file = "song_configs.json"
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    self.song_configs = json.load(f)
        except Exception as e:
            print(f"加载歌曲配置失败: {e}")
            self.song_configs = {}
    
    def save_song_configs(self):
        """保存歌曲配置"""
        try:
            config_file = "song_configs.json"
            # 深拷贝避免递归
            configs_to_save = {}
            for key, value in self.song_configs.items():
                if isinstance(value, dict):
                    configs_to_save[key] = {k: v for k, v in value.items() 
                                           if not callable(v) and not hasattr(v, '__dict__')}
                else:
                    configs_to_save[key] = value
            
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(configs_to_save, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存歌曲配置失败: {e}")
            import traceback
            traceback.print_exc()
    
    def on_closing(self):
        """窗口关闭事件"""
        self.save_song_configs()
        self.player.clean_temp_files()
        self.root.destroy()
    
    def setup_styles(self):
        """设置界面样式"""
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TButton", padding=5, font=('微软雅黑', 10))
        style.configure("TLabel", font=('微软雅黑', 10))
        style.configure("TFrame", background='#f0f0f0')
        style.configure("Treeview", font=('微软雅黑', 10), rowheight=25)
        style.configure("Treeview.Heading", font=('微软雅黑', 10, 'bold'))
        
    def create_menu_bar(self):
        """创建菜单栏"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # 文件菜单
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="文件", menu=file_menu)
        file_menu.add_command(label="打开文件", command=self.open_files, accelerator="Ctrl+O")
        file_menu.add_command(label="打开文件夹", command=self.open_folder, accelerator="Ctrl+Shift+O")
        file_menu.add_command(label="导入文件夹到列表", command=self.import_folder_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="快捷键设置", command=self.show_shortcut_settings)
        file_menu.add_command(label="灯光控制", command=self.show_light_control)
        file_menu.add_command(label="设置", command=self.show_settings)
        file_menu.add_separator()
        file_menu.add_command(label="前缀音缓存管理", command=self.show_cache_manager)  # 新增
        file_menu.add_command(label="清理临时文件", command=self.clean_temp_files)
        file_menu.add_command(label="退出", command=self.on_closing)
        
        # 播放菜单
        play_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="播放", menu=play_menu)
        play_menu.add_command(label="播放", command=self.play_music, accelerator="Space")
        play_menu.add_command(label="暂停", command=self.pause_music)
        play_menu.add_command(label="停止", command=self.stop_music)
        play_menu.add_separator()
        play_menu.add_command(label="上一首", command=self.previous_song, accelerator="Left")
        play_menu.add_command(label="下一首", command=self.next_song, accelerator="Right")
        play_menu.add_separator()
        
        # ✅ 修改：前缀音配置 - 改为打开配置弹窗，不带复选框
        play_menu.add_command(label="前缀音配置", command=self.show_prefix_config_dialog)
        
        # ✅ 新增：前缀音播放子菜单
        self.prefix_play_submenu = tk.Menu(play_menu, tearoff=0)
        play_menu.add_cascade(label="前缀音播放", menu=self.prefix_play_submenu)
        self._update_prefix_play_submenu()  # 更新子菜单内容
        # ✅ 关闭前缀音 - 保存菜单项引用

        self._close_prefix_menu_index = play_menu.index("end")  # 记录索引

        play_menu.add_command(label="关闭前缀音", command=self.disable_prefix_audio)
        # ✅ 初始化状态为禁用（灰色）
        play_menu.entryconfig(self._close_prefix_menu_index + 1, state=tk.DISABLED)

        play_menu.add_separator()
        
        # 播放模式子菜单
        self.play_mode_submenu = tk.Menu(play_menu, tearoff=0)
        self.play_mode_submenu.add_command(label="▶ 顺序播放", command=lambda: self.set_play_mode("sequential"))
        self.play_mode_submenu.add_command(label="  单曲循环", command=lambda: self.set_play_mode("single_loop"))
        self.play_mode_submenu.add_command(label="  随机播放", command=lambda: self.set_play_mode("random"))
        play_menu.add_cascade(label="播放模式", menu=self.play_mode_submenu)

        # ✅ 保存播放菜单引用
        self._play_menu = play_menu

        # 播放列表菜单
        tracklist_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="播放列表", menu=tracklist_menu)
        tracklist_menu.add_command(label="新建播放列表", command=self.create_new_playlist)
        tracklist_menu.add_separator()
        tracklist_menu.add_command(label="重命名播放列表", command=self.rename_current_playlist)
        tracklist_menu.add_separator()
        tracklist_menu.add_command(label="删除当前播放列表", command=self.delete_current_playlist)
        
        # 歌库操作菜单
        library_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="歌库操作", menu=library_menu)
        library_menu.add_command(label="搜索歌曲", command=self.search_songs, accelerator="Ctrl+F")
        library_menu.add_command(label="打开文件所在目录", command=self.open_file_location)
        library_menu.add_separator()
        library_menu.add_command(label="按舞种顺序生成歌单", command=self.show_dance_order_generator)
        library_menu.add_separator()
        library_menu.add_command(label="发送到临时列表并播放", command=self.send_to_temp_and_play)
        library_menu.add_command(label="设置歌库目录", command=self.set_library_dir)
        library_menu.add_command(label="重命名", command=self.rename_file)
        library_menu.add_separator()
        library_menu.add_command(label="删除文件", command=self.delete_file)
        
        # 关于菜单
        about_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="关于", menu=about_menu)
        about_menu.add_command(label="软件信息", command=self.show_about)
        about_menu.add_command(label="使用帮助", command=self.show_help)
        about_menu.add_command(label="检查更新", command=self.check_updates)
        
    def create_control_bar(self):
        """创建控制栏"""
        control_frame = tk.Frame(self.root, bg='#ecf0f1', height=35)
        control_frame.pack(fill=tk.X, pady=5)
        control_frame.pack_propagate(False)
        
        # 左侧：图标按钮
        left_controls = tk.Frame(control_frame, bg='#ecf0f1')
        left_controls.pack(side=tk.LEFT, padx=20)
        
        # 播放按钮
        self.play_btn = tk.Button(left_controls, text="▶", 
                            bg='#2ecc71', fg='white',
                            font=('Arial', 10, 'bold'),
                            relief=tk.RAISED, cursor='hand2',
                            width=2, height=1,
                            command=self.play_music)
        self.play_btn.pack(side=tk.LEFT, padx=8)
        self.bind_hover(self.play_btn, "播放：带滑入播放，使用空格键播放/暂停，使用左右方向键切换上一首/下一首")
        
        # 暂停按钮
        self.pause_btn = tk.Button(left_controls, text="⏸", 
                             bg='#f39c12', fg='white',
                             font=('Arial', 10),
                             relief=tk.RAISED, cursor='hand2',
                             width=2, height=1,
                             command=self.pause_music)
        self.pause_btn.pack(side=tk.LEFT, padx=8)
        self.bind_hover(self.pause_btn, "暂停：带滑出暂停，继续播放会在暂停的位置开始播放")
        
        # 停止按钮
        self.stop_btn = tk.Button(left_controls, text="⏹", 
                            bg='#e74c3c', fg='white',
                            font=('Arial', 10),
                            relief=tk.RAISED, cursor='hand2',
                            width=2, height=1,
                            command=self.stop_music)
        self.stop_btn.pack(side=tk.LEFT, padx=8)
        self.bind_hover(self.stop_btn, "停止：点击停止按钮可重头播放舞曲，单击软停止，双击硬停止")
        self.stop_btn.bind('<Double-1>', self.on_stop_double_click)  # 双击触发硬停止
        
        # 中间：进度条
        progress_frame = tk.Frame(control_frame, bg='#ecf0f1')
        progress_frame.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=20)
        
        # 当前时间标签
        self.current_time_label = tk.Label(progress_frame, text="00:00", 
                                          bg='#ecf0f1', font=('微软雅黑', 10))
        self.current_time_label.pack(side=tk.LEFT, padx=5)

        
        # 进度条（播放过的就是填充色）
        self.progress_bar = ttk.Progressbar(progress_frame, length=400, mode='determinate')
        self.progress_bar.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
        self.bind_hover(self.progress_bar, "进度条：仅显示播放时长区段，且时长会随速度快慢而自动增减，无滑块，不可点击拖动调整播放位置")
        
        self.total_time_label = tk.Label(progress_frame, text="00:00", 
                                        bg='#ecf0f1', font=('微软雅黑', 10))
        self.total_time_label.pack(side=tk.LEFT, padx=5)
        
        # 右侧：音量调节
        volume_frame = tk.Frame(control_frame, bg='#ecf0f1')
        volume_frame.pack(side=tk.RIGHT, padx=10)
               
        # 音量滑块
        self.volume_scale = tk.Scale(volume_frame, from_=0, to=100, 
                       orient=tk.HORIZONTAL, length=100,
                       bg='#ecf0f1', highlightthickness=0,
                       showvalue=0,          # 告诉 Tkinter 不要显示当前数值
                       command=self.change_volume)
        self.volume_scale.set(80)
        self.volume_scale.pack(side=tk.LEFT)
        self.bind_hover(self.volume_scale, "音量调节：F2减少音量，F3增加音量")
        
        # 辅助信息状态栏
        self.helper_frame = tk.Frame(self.root, bg='#d5dbdb', height=25)
        self.helper_frame.pack(fill=tk.X, padx=5, pady=(0, 5))
        self.helper_frame.pack_propagate(False)
        
        self.helper_label = tk.Label(self.helper_frame, text="", 
                                    bg='#d5dbdb', fg='#2c3e50',
                                    font=('微软雅黑', 9),
                                    anchor='w')
        self.helper_label.pack(fill=tk.BOTH, expand=True, padx=10)
        
    def bind_hover(self, widget, text):
        """为控件绑定悬停事件"""
        def on_enter(event):
            self.helper_label.config(text=text)
        
        def on_leave(event):
            self.helper_label.config(text="")
        
        widget.bind('<Enter>', on_enter)
        widget.bind('<Leave>', on_leave)
        
    def create_main_content(self):
        """创建主要内容区域（使用PanedWindow实现可调整大小）"""
        # 创建水平PanedWindow
        self.main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 左侧：文件夹目录
        self.left_frame = tk.Frame(self.main_paned, bg='white', relief=tk.SUNKEN, borderwidth=1)
        self.left_frame.pack_propagate(False)
        self.main_paned.add(self.left_frame, weight=1)
        
        # 文件夹树形视图容器
        folder_container = tk.Frame(self.left_frame, bg='white')
        folder_container.pack(fill=tk.BOTH, expand=True)
        
        # 文件夹树形视图
        self.folder_tree = ttk.Treeview(folder_container, selectmode='browse')
        self.folder_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.folder_tree.heading('#0', text='文件夹', anchor='w')
        self.bind_hover(self.folder_tree, "歌库文件夹列表：单击文件即可快速添加到当前播放列表，菜单栏【文件】-【导入文件夹到列表】可将文件夹内所有音乐添加到当前播放列表")
        
        # 添加滚动条
        folder_scrollbar = ttk.Scrollbar(folder_container, orient="vertical", 
                                        command=self.folder_tree.yview)
        self.folder_tree.configure(yscrollcommand=folder_scrollbar.set)
        folder_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 绑定文件夹选择事件
        self.folder_tree.bind('<<TreeviewSelect>>', self.on_folder_select)
        self.folder_tree.bind('<Double-1>', self.on_folder_double_click)
        
        # 右侧：播放列表区域
        self.right_frame = tk.Frame(self.main_paned, bg='white', relief=tk.SUNKEN, borderwidth=1)
        self.main_paned.add(self.right_frame, weight=8)
        
        # 创建垂直PanedWindow用于右侧上下分割
        self.right_paned = ttk.PanedWindow(self.right_frame, orient=tk.VERTICAL)
        self.right_paned.pack(fill=tk.BOTH, expand=True)
        
        # 顶部：播放列表按钮区域
        self.top_btn_frame = tk.Frame(self.right_paned, bg='#ecf0f1', height=40)
        self.top_btn_frame.pack_propagate(False)
        self.right_paned.add(self.top_btn_frame, weight=0)

        #  创建滚动容器
        canvas_frame = tk.Frame(self.top_btn_frame, bg='#ecf0f1')
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建 Canvas
        self.playlist_canvas = tk.Canvas(canvas_frame, bg='#ecf0f1', height=40, highlightthickness=0)
        
        # 创建水平滚动条
        self.playlist_scrollbar = tk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, 
                                            command=self.playlist_canvas.xview)
        self.playlist_canvas.configure(xscrollcommand=self.playlist_scrollbar.set)
        
        # 创建内部框架（用于放置按钮）
        self.playlist_inner_frame = tk.Frame(self.playlist_canvas, bg='#ecf0f1')
        
        # 将内部框架放入 Canvas
        self.canvas_window = self.playlist_canvas.create_window((0, 0), window=self.playlist_inner_frame, anchor='nw')
        
        # 布局 Canvas 和滚动条
        self.playlist_canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.playlist_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        #  更新滚动区域
        def configure_scroll_region(event):
            self.playlist_canvas.configure(scrollregion=self.playlist_canvas.bbox('all'))
            # 更新 Canvas 宽度
            canvas_width = self.playlist_canvas.winfo_width()
            inner_width = self.playlist_inner_frame.winfo_reqwidth()
            # 使用较大的宽度，确保滚动条正常工作
            self.playlist_canvas.itemconfig(self.canvas_window, width=max(canvas_width, inner_width))
        
        self.playlist_inner_frame.bind('<Configure>', configure_scroll_region)
        self.playlist_canvas.bind('<Configure>', configure_scroll_region)
        self.bind_hover(self.playlist_inner_frame, "💡 在此区域滚动鼠标滚轮可左右浏览更多播放列表")
        self.bind_hover(self.playlist_canvas, "💡 在此区域滚动鼠标滚轮可左右浏览更多播放列表")

        #  鼠标滚轮支持
        def on_mousewheel(event):
            # 检查是否有水平滚动条
            if self.playlist_canvas.winfo_width() < self.playlist_inner_frame.winfo_reqwidth():
                self.playlist_canvas.xview_scroll(int(-1 * (event.delta / 120)), 'units')
        
        self.playlist_canvas.bind('<MouseWheel>', on_mousewheel)
        self.playlist_inner_frame.bind('<MouseWheel>', on_mousewheel)
        
        # 更新 playlist_buttons 的父容器引用
        self.playlist_buttons_frame = self.playlist_inner_frame
        self.playlist_buttons = {}
        self.update_playlist_buttons()
        
        # 中间：舞曲编排表格
        self.top_frame = tk.Frame(self.right_paned, bg='white')
        self.right_paned.add(self.top_frame, weight=3)
        
        self.top_frame.grid_rowconfigure(0, weight=1)
        self.top_frame.grid_columnconfigure(0, weight=1)
        
        table_container = tk.Frame(self.top_frame, bg='white')
        table_container.grid(row=0, column=0, sticky='nsew')
        table_container.grid_rowconfigure(0, weight=1)
        table_container.grid_columnconfigure(0, weight=1)
        
        self.create_song_table_in_container(table_container)
        
        # 底部：音频控制
        self.bottom_frame = tk.Frame(self.right_paned, bg='white', relief=tk.GROOVE, borderwidth=1)
        self.bottom_frame.pack_propagate(False)
        self.right_paned.add(self.bottom_frame, weight=1)
        
        audio_container = tk.Frame(self.bottom_frame, bg='white')
        audio_container.pack(fill=tk.BOTH, expand=True)
        
        self.create_audio_controls(audio_container)
        
        self.load_playlist(1)

    def create_song_table_in_container(self, container):
        """在指定容器中创建舞曲编排表格"""
        columns = ('序号', '播放时间', '歌名', '歌曲时长', '起始时间', 
                '播放时长', '停顿时长', '音量', '速度', '音调', '灯光')
        
        self.song_table = ttk.Treeview(container, columns=columns, show='headings', height=15)
        
        # 设置列标题
        for col in columns:
            self.song_table.heading(col, text=col)
        
        # 设置列宽
        self.song_table.column('序号', width=15, anchor='center')
        self.song_table.column('播放时间', width=50, anchor='center')
        self.song_table.column('歌名', width=450, anchor='w')
        self.song_table.column('歌曲时长', width=50, anchor='center')
        self.song_table.column('起始时间', width=50, anchor='center')
        self.song_table.column('播放时长', width=50, anchor='center')
        self.song_table.column('停顿时长', width=50, anchor='center')
        self.song_table.column('音量', width=30, anchor='center')
        self.song_table.column('速度', width=30, anchor='center')
        self.song_table.column('音调', width=30, anchor='center')
        self.song_table.column('灯光', width=20, anchor='center')

        # 添加垂直滚动条
        table_vscrollbar = ttk.Scrollbar(container, orient="vertical", 
                                        command=self.song_table.yview)
        self.song_table.configure(yscrollcommand=table_vscrollbar.set)

        # 添加水平滚动条
        table_hscrollbar = ttk.Scrollbar(container, orient="horizontal", 
                                        command=self.song_table.xview)
        self.song_table.configure(xscrollcommand=table_hscrollbar.set)

        # 布局表格和滚动条
        self.song_table.grid(row=0, column=0, sticky='nsew')
        table_vscrollbar.grid(row=0, column=1, sticky='ns')
        table_hscrollbar.grid(row=1, column=0, sticky='ew')

        # 配置网格权重
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        # 绑定鼠标点击事件        
        self.song_table.bind('<Double-1>', self.on_table_double_click)
        self.song_table.bind('<Button-3>', self.show_table_context_menu)
        self.song_table.bind('<<TreeviewSelect>>', self.on_song_select)
        self.bind_hover(self.song_table, "舞曲编排表格：双击播放，拖动舞曲可以调整播放次序，右键菜单进行管理")

        # 绑定拖动排序事件
        self.song_table.bind('<Button-1>', self.on_table_drag_start)
        self.song_table.bind('<B1-Motion>', self.on_table_drag_motion)
        self.song_table.bind('<ButtonRelease-1>', self.on_table_drag_end)

    def create_audio_controls(self, container):
        """创建音频控制"""
        # 左：七段均衡器
        eq_frame = tk.Frame(container, bg='white', relief=tk.GROOVE, borderwidth=1)
        eq_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        eq_frame.bind('<Button-3>', self.show_eq_context_menu)
        self.bind_hover(eq_frame, "七段均衡器（暂不可用）：均衡效果仅对当前舞曲有效，并自动保存到舞曲中，右键可重置")
                
        eq_frequencies = ['60Hz', '150Hz', '400Hz', '1kHz', '2.4kHz', '6kHz', '15kHz']
        self.eq_sliders = []
        eq_sliders_frame = tk.Frame(eq_frame, bg='white')
        eq_sliders_frame.pack(pady=10)
        
        for i, freq in enumerate(eq_frequencies):
            slider_frame = tk.Frame(eq_sliders_frame, bg='white')
            slider_frame.pack(side=tk.LEFT, padx=2)
            
            slider = tk.Scale(slider_frame, from_=-12, to=12, orient=tk.VERTICAL, 
                            length=90, bg='white', highlightthickness=0,
                            command=lambda v, idx=i: self.on_eq_change(idx, v))
            slider.set(0)
            slider.pack()
            self.eq_sliders.append(slider)
            self.bind_hover(slider, f"均衡器 {freq}")
            
            tk.Label(slider_frame, text=freq, bg='white', font=('微软雅黑', 8)).pack()
        
        # 左声道VU表（独立frame）
        left_vu_frame = tk.Frame(container, bg="#f9fbfc", relief=tk.GROOVE, borderwidth=1)
        left_vu_frame.pack(side=tk.LEFT, fill=tk.NONE, padx=2, pady=5)
        tk.Label(left_vu_frame, text="L", bg="#f9fbfc",fg='#0B0B0B', 
                font=('Arial', 8, 'bold')).pack(side=tk.TOP, pady=1)
        self.left_vu_meter = VUMeter(left_vu_frame, width=20, height=80, bg="#0B0B0B")
        self.left_vu_meter.pack(side=tk.TOP, pady=5, padx=5)
        self.bind_hover(self.left_vu_meter, "左声道VU表")

        # 中：音频调节
        tempo_frame = tk.Frame(container, bg='white', relief=tk.GROOVE, borderwidth=1)
        tempo_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        tempo_frame.bind('<Button-3>', self.show_tempo_context_menu)
        self.bind_hover(tempo_frame, "音频调节：变速不变调，变调不变速，仅对当前舞曲有效，并自动保存到舞曲中，右键可重置")

        # 节拍滑块
        tk.Label(tempo_frame, text="节拍", bg='white').pack(anchor='c', pady=(0, 0))
        self.beat_slider = ttk.Scale(tempo_frame, from_=30, to=150,
                                    orient=tk.HORIZONTAL,
                                    command=self.on_beat_change)
        self.beat_slider.set(90)
        self.beat_slider.pack(pady=(0, 5), fill=tk.X, padx=5)
        self.bind_hover(self.beat_slider, "节拍调节（占位）")

        # 速度滑块
        tk.Label(tempo_frame, text="速度", bg='white').pack(anchor='c', pady=(0, 0))
        self.speed_slider = ttk.Scale(tempo_frame, from_=50, to=150,
                                    orient=tk.HORIZONTAL,
                                    command=self.on_speed_change)
        self.speed_slider.set(100)
        self.speed_slider.pack(pady=(0, 5), fill=tk.X, padx=5)
        self.bind_hover(self.speed_slider, "速度调节，释放鼠标应用")
        self.speed_slider.bind('<ButtonRelease-1>', self.on_speed_slider_release)

        # 音调滑块
        tk.Label(tempo_frame, text="音调", bg='white').pack(anchor='c', pady=(0, 0))
        self.pitch_slider = ttk.Scale(tempo_frame, from_=-12, to=12,
                                    orient=tk.HORIZONTAL,
                                    command=self.on_pitch_change)
        self.pitch_slider.set(0)
        self.pitch_slider.pack(pady=(0, 5), fill=tk.X, padx=5)
        self.bind_hover(self.pitch_slider, "音调调节，释放鼠标应用")
        self.pitch_slider.bind('<ButtonRelease-1>', self.on_pitch_slider_release)

        # 右声道VU表（独立frame）
        right_vu_frame = tk.Frame(container, bg="#f9fbfc", relief=tk.GROOVE, borderwidth=1)
        right_vu_frame.pack(side=tk.LEFT, fill=tk.NONE, padx=2, pady=5)
        tk.Label(right_vu_frame, text="R", bg='#f9fbfc', fg="#0B0B0B", 
                font=('Arial', 8, 'bold')).pack(side=tk.TOP, pady=1)
        self.right_vu_meter = VUMeter(right_vu_frame, width=20, height=80, bg='#0B0B0B')
        self.right_vu_meter.pack(side=tk.TOP, pady=5, padx=5)
        self.bind_hover(self.right_vu_meter, "右声道VU表")

        # 右：歌曲信息
        metadata_frame = tk.Frame(container, bg='white', relief=tk.GROOVE, borderwidth=1)
        metadata_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.bind_hover(metadata_frame, "歌曲信息")

        self.metadata_text = tk.Text(metadata_frame, font=('微软雅黑', 9), 
                                    bg='#f8f9fa', wrap=tk.WORD, height=15)
        self.metadata_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.bind_hover(self.metadata_text, "歌曲元数据信息")

    def update_vu_meter_thread(self):
        """更新VU表线程"""
        def update_vu():
            while True:
                try:
                    if self.player.is_playing and not self.player.is_paused:
                        left_level, right_level = self.player.get_audio_levels()
                        volume_factor = self.player.volume / 100.0
                        left_level *= volume_factor
                        right_level *= volume_factor
                        self.root.after(0, self.update_vu_meters, left_level, right_level)
                    else:
                        self.root.after(0, self.update_vu_meters, 0.0, 0.0)
                except Exception as e:
                    print(f"VU表更新错误: {e}")
                
                time.sleep(0.1)
        
        thread = threading.Thread(target=update_vu, daemon=True)
        thread.start()
    
    def update_vu_meters(self, left_level, right_level):
        """更新VU表显示"""
        try:
            self.left_vu_meter.set_level(left_level)
            self.right_vu_meter.set_level(right_level)
        except Exception as e:
            print(f"更新VU表显示错误: {e}")

    def show_eq_context_menu(self, event):
        """显示七段均衡器的右键菜单"""
        eq_menu = tk.Menu(self.root, tearoff=0)
        eq_menu.add_command(label="重置均衡器", command=self.reset_eq)
        eq_menu.post(event.x_root, event.y_root)

    def show_tempo_context_menu(self, event):
        """显示音频调节的右键菜单"""
        tempo_menu = tk.Menu(self.root, tearoff=0)
        tempo_menu.add_command(label="重置音频调节", command=self.reset_tempo)
        tempo_menu.post(event.x_root, event.y_root)

    def update_playlist_buttons(self):
        """更新播放列表按钮（支持拖放排序）"""
        #  使用 inner_frame 而不是 top_btn_frame
        container = getattr(self, 'playlist_buttons_frame', self.top_btn_frame)
        
        for widget in container.winfo_children():
            widget.destroy()
        
        colors = ['#3498db', '#2ecc71', '#e67e22', '#9b59b6', '#e74c3c', '#1abc9c', '#e84393', '#00b894']
        self.playlist_buttons = {}
        
        #  获取所有播放列表ID，并按存储顺序排序（不是按数字排序），且确保临时列表（ID=1）在第一位
        playlist_ids = list(self.playlist_manager.playlists.keys())
        # 确保临时列表（ID=1）在第一位

        if 1 in playlist_ids:
            playlist_ids.remove(1)
            playlist_ids.insert(0, 1)
        
        for i, playlist_id in enumerate(playlist_ids):
            playlist_data = self.playlist_manager.playlists[playlist_id]
            color = colors[i % len(colors)]
            
            # ✅ 根据文字长度计算按钮宽度
            # text_len = len(playlist_data["name"])
            # btn_width = max(5, min(10, text_len * 12 + 20))
            # ✅ 修复：使用 text 宽度自适应（不设置 width 参数）

            btn = tk.Button(container, text=playlist_data["name"], 
                            bg=color, fg='white',
                            font=('微软雅黑', 10, 'bold'),
                            relief=tk.RAISED, cursor='hand2',
                            padx=10,  # 使用 padx 控制内边距
                            height=1,
                            command=lambda id=playlist_id: self.load_playlist(id))
            btn.pack(side=tk.LEFT, padx=5, pady=5)
            btn.bind('<Button-3>', lambda e, id=playlist_id: self.show_playlist_context_menu(e, id))
            
            # ✅ 临时列表不绑定拖放事件
            if playlist_id != 1:
                btn.bind('<Button-1>', lambda e, id=playlist_id: self.on_playlist_drag_start(e, id))
                btn.bind('<B1-Motion>', self.on_playlist_drag_motion)
                btn.bind('<ButtonRelease-1>', self.on_playlist_drag_end)
                
                self.playlist_buttons[playlist_id] = btn
                self.bind_hover(btn, f"播放列表: {playlist_data['name']}，右键菜单进行管理，拖放可调整位置，支持滚轮和滚动条查看列表标签")
            else:
                self.bind_hover(btn, f"临时列表（默认列表，固定在首位，不可移动，不能删除，，不播放前缀音，在非播放列表下不能进行播放控制操作，）")
            
            self.playlist_buttons[playlist_id] = btn

        # ✅ 强制更新布局，确保滚动区域正确
        container.update_idletasks()
        if hasattr(self, 'playlist_canvas'):
            self.playlist_canvas.configure(scrollregion=self.playlist_canvas.bbox('all'))
            
    # ==================== 拖放方法 ====================

    def on_playlist_drag_start(self, event, playlist_id):
        """播放列表标签拖放开始"""
        # ✅ 临时列表（ID=1）不允许拖动
        if playlist_id == 1:
            self.status_label.config(text="临时列表固定在首位，不可移动")
            self._drag_playlist_start = None
            self._drag_playlist_widget = None
            return
        widget = event.widget
        self._drag_playlist_start = playlist_id
        self._drag_playlist_widget = widget
        
        self._drag_playlist_offset_x = event.x
        self._drag_playlist_offset_y = event.y
        
        widget.lift()
        widget.config(relief=tk.RAISED, bd=3)

    def on_playlist_drag_motion(self, event):
        """播放列表标签拖放过程中"""
        if self._drag_playlist_widget is None:
            return
        
        parent = self._drag_playlist_widget.master
        
        x = event.x_root - parent.winfo_rootx() - self._drag_playlist_offset_x
        y = event.y_root - parent.winfo_rooty() - self._drag_playlist_offset_y
        
        self._drag_playlist_widget.place(x=x, y=y)
        self._highlight_target(event.x_root, event.y_root)

    def on_playlist_drag_end(self, event):
        """播放列表标签拖放结束"""
        # 清除指示器
        self._clear_highlight()
        if self._drag_playlist_widget is None:
            self._drag_playlist_start = None
            return
        
        try:
            # 隐藏浮动的按钮
            self._drag_playlist_widget.place_forget()
            self._drag_playlist_widget.config(relief=tk.RAISED, bd=1)
        except:
            pass
        
        # 获取目标ID
        target_id = self._get_playlist_at_position(event.x_root, event.y_root)
        
        # if target_id is not None and target_id != self._drag_playlist_start:
        # ✅ 不能移动到临时列表（ID=1）的位置
        if target_id == 1:
            self.status_label.config(text="不能移动到临时列表的位置")
            self._reorder_buttons(list(self.playlist_manager.playlists.keys()))
        elif target_id is not None and target_id != self._drag_playlist_start:

            self._insert_playlist(self._drag_playlist_start, target_id)
        else:
            # 没有移动，恢复按钮位置
            self._reorder_buttons(list(self.playlist_manager.playlists.keys()))
        
        # 重置拖放状态
        self._drag_playlist_start = None
        self._drag_playlist_widget = None

    def _highlight_target(self, x, y):
        """高亮目标按钮"""
        self._clear_highlight()
        
        target_id = self._get_playlist_at_position(x, y)
        if target_id is None or target_id == 1:
            return
        
        btn = self.playlist_buttons.get(target_id)
        if btn is None or not btn.winfo_exists():
            return
        
        self._highlight_target_id = target_id
        try:
            # 使用更明显的视觉提示
            btn.config(
                bg='#FFD700',  # 金色高亮
                relief=tk.SUNKEN,
                bd=4,
                fg='#000000'  # 黑色文字
            )
            # 添加边框效果
            btn.lift()
        except:
            pass

    def _clear_highlight(self):
        """清除所有高亮"""
        if hasattr(self, '_highlight_target_id') and self._highlight_target_id is not None:
            target = self._highlight_target_id
            btn = self.playlist_buttons.get(target)
            if btn and btn.winfo_exists():
                colors = ['#3498db', '#2ecc71', '#e67e22', '#9b59b6', '#e74c3c', '#1abc9c', '#e84393', '#00b894']
                playlist_ids = list(self.playlist_buttons.keys())
                if target in playlist_ids:
                    idx = playlist_ids.index(target) % len(colors)
                    try:
                        btn.config(
                            bg=colors[idx],
                            relief=tk.RAISED,
                            bd=1,
                            fg='white'
                        )
                    except:
                        pass
            self._highlight_target_id = None

    def _get_playlist_at_position(self, x, y):
        """获取鼠标位置所在的播放列表ID"""
        for playlist_id, btn in self.playlist_buttons.items():
            # 检查按钮是否有效
            if btn is None:
                continue
            try:
                if not btn.winfo_exists() or not btn.winfo_ismapped():
                    continue
                btn_x = btn.winfo_rootx()
                btn_y = btn.winfo_rooty()
                btn_width = btn.winfo_width()
                btn_height = btn.winfo_height()
                if btn_width == 0 or btn_height == 0:
                    continue
                if (btn_x - 5 <= x <= btn_x + btn_width + 5 and 
                    btn_y - 5 <= y <= btn_y + btn_height + 5):
                    return playlist_id
            except:
                continue
        return None

    def _insert_playlist(self, from_id, to_id):
        """插入式排序：将播放列表移动到目标位置"""
        if from_id == to_id:
            return
        #  临时列表不能被移动
        if from_id == 1 or to_id == 1:
            self.status_label.config(text="临时列表固定在首位，不可移动")
            return
        # 获取所有播放列表ID（按当前显示顺序）
        playlist_ids = list(self.playlist_manager.playlists.keys())
        # 确保临时列表始终在第一位
        if 1 in playlist_ids:
            # 如果临时列表不在第一位，把它移到第一位
            playlist_ids.remove(1)
            playlist_ids.insert(0, 1)
        # ... 后续循环使用 playlist_ids ...

        from_index = playlist_ids.index(from_id)
        to_index = playlist_ids.index(to_id)
        # 重新排序ID列表
        playlist_ids.pop(from_index)
        playlist_ids.insert(to_index, from_id)
        # 创建新的有序字典
        new_playlists = {}
        for pid in playlist_ids:
            new_playlists[pid] = self.playlist_manager.playlists[pid]
        
        self.playlist_manager.playlists = new_playlists
        self.playlist_manager.save_playlists()
        # 直接重新排列按钮
        self._reorder_buttons(playlist_ids)
        
        list_name = self.playlist_manager.playlists[from_id]['name']
        self.status_label.config(text=f"📌 已移动: {list_name} → 位置 {to_index + 1}")

    def _reorder_buttons(self, playlist_ids):
        """重新排列按钮（不重建）"""
        container = getattr(self, 'playlist_buttons_frame', self.top_btn_frame)
        # 按新顺序重新 pack 按钮,且确保临时列表在第一位
        if 1 in playlist_ids:
            playlist_ids.remove(1)
            playlist_ids.insert(0, 1)
        # 先全部从布局中移除
        for pid in list(self.playlist_buttons.keys()):
            btn = self.playlist_buttons.get(pid)
            if btn and btn.winfo_exists():
                try:
                    btn.pack_forget()
                except:
                    pass
        # 按新顺序重新 pack
        for pid in playlist_ids:
            btn = self.playlist_buttons.get(pid)
            if btn and btn.winfo_exists():
                try:
                    btn.pack(side=tk.LEFT, padx=5, pady=5)
                except:
                    pass
        # 更新当前播放列表的高亮
        for pid, btn in self.playlist_buttons.items():
            if btn and btn.winfo_exists():
                try:
                    if pid == self.current_playlist:
                        btn.config(relief=tk.SUNKEN)
                    else:
                        btn.config(relief=tk.RAISED)
                except:
                    pass
        
        try:
            container.update_idletasks()
        except:
            pass

    def create_status_bar(self):
        """创建底部状态栏"""
        self.status_frame = tk.Frame(self.root, bg='#2c3e50', height=30)
        self.status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_frame.pack_propagate(False)
        
        # 时间
        self.status_time_label = tk.Label(self.status_frame, text="", 
                                    bg='#2c3e50', fg='white',
                                    font=('微软雅黑', 9))
        self.status_time_label.pack(side=tk.LEFT, padx=5)

        # ✅ 新增：前缀音状态显示
        self.status_prefix_label = tk.Label(self.status_frame, text="前缀音: 关", 
                                        bg='#2c3e50', fg='#7f8c8d',
                                        font=('微软雅黑', 10, 'bold'))
        self.status_prefix_label.pack(side=tk.LEFT, padx=15)

        # 播放模式
        self.status_play_mode_label = tk.Label(self.status_frame, text="播放模式: 顺序播放", 
                                            bg='#2c3e50', fg='#9b59b6',
                                            font=('微软雅黑', 10, 'bold'))
        self.status_play_mode_label.pack(side=tk.LEFT, padx=15)

        # 播放位置
        self.status_position_label = tk.Label(self.status_frame, text="0/0", 
                                            bg='#2c3e50', fg='#e67e22',
                                            font=('微软雅黑', 10, 'bold'))
        self.status_position_label.pack(side=tk.LEFT, padx=5)

        # 播放时间
        self.status_time_display_label = tk.Label(self.status_frame, text="00:00 / 00:00", 
                                                bg='#2c3e50', fg='#2ecc71',
                                                font=('微软雅黑', 10))
        self.status_time_display_label.pack(side=tk.LEFT, padx=5)

        # 进度百分比
        self.percent_label = tk.Label(self.status_frame, text="0%", 
                                    bg='#2c3e50', fg='#e74c3c',
                                    font=('微软雅黑', 10, 'bold'), width=6)
        self.percent_label.pack(side=tk.LEFT, padx=5)

        # 状态信息（右侧）
        self.status_label = tk.Label(self.status_frame, text="就绪", 
                                bg='#2c3e50', fg='white',
                                font=('微软雅黑', 10))
        self.status_label.pack(side=tk.RIGHT, padx=10)
        
        self.update_time()
        
    def setup_shortcuts(self):
        """设置快捷键"""
        self.root.bind('<Control-o>', lambda e: self.open_files())
        self.root.bind('<Control-Shift-O>', lambda e: self.open_folder())
        self.root.bind('<Control-f>', lambda e: self.search_songs())
        self.root.bind('<F2>', lambda e: self.decrease_volume())
        self.root.bind('<F3>', lambda e: self.increase_volume())
        self.root.bind('<space>', lambda e: self.toggle_play_pause())
        self.root.bind('<Left>', lambda e: self.previous_song())
        self.root.bind('<Right>', lambda e: self.next_song())
        self.root.bind('<F4>', lambda e: self.jump_to_playing_playlist())
        self.root.bind('<Delete>', lambda e: self.delete_selected())

    def jump_to_playing_playlist(self):
        """跳转到当前正在播放的播放列表"""
        if not self.player.is_playing and not self.player.is_paused:
            self.status_label.config(text="当前没有播放任何歌曲")
            return
        
        if self.player.current_index < 0:
            self.status_label.config(text="当前没有播放任何歌曲")
            return
        
        # 获取当前播放歌曲
        current_song = getattr(self.player, 'current_file', None)
        if not current_song:
            self.status_label.config(text="无法确定当前播放的歌曲")
            return
        
        # 查找包含当前播放歌曲的播放列表
        for playlist_id, playlist_data in self.playlist_manager.playlists.items():
            if current_song in playlist_data["songs"]:
                # 切换到这个列表
                self.load_playlist(playlist_id)
                
                # 高亮当前播放的歌曲
                if self.player.current_index >= 0:
                    items = self.song_table.get_children()
                    if self.player.current_index < len(items):
                        self.song_table.selection_set(items[self.player.current_index])
                        self.song_table.see(items[self.player.current_index])
                
                self.status_label.config(text=f"✅ 已返回正在播放的列表: {playlist_data['name']}")
                return
        
        self.status_label.config(text="未找到当前播放歌曲所在的列表")

    def toggle_play_pause(self):
        """切换播放/暂停"""
        # ✅ 检查是否为正在播放的列表
        if not self._is_current_playlist_playable():
            self.status_label.config(text="⚠️ 当前列表不是正在播放的列表，无法操作")
            return
        
        if self.player.is_playing:
            self.pause_music()
        elif self.player.is_paused:
            self.pause_music()
        else:
            self.play_music()

    def setup_drag_drop(self):
        """设置拖放功能"""
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self.on_drop)
        except:
            pass
    
    # ==================== 歌曲选择事件 ====================
    
    def on_song_select(self, event):
        """歌曲选择事件 - 更新速度音调滑块"""
        if self._updating_sliders:
            return
            
        song_path = self.get_selected_song_path()
        if song_path:
            config = self.song_configs.get(song_path, {})
            speed = config.get('speed', self.default_settings['speed'])
            pitch = config.get('pitch', self.default_settings['pitch'])
            volume = config.get('volume', self.default_settings['volume'])
            
            self._updating_sliders = True
            self.speed_slider.set(speed)
            self.pitch_slider.set(pitch)
            self.volume_scale.set(volume)
            self._updating_sliders = False
    
    # ==================== 音频控制事件 ====================
    
    def reset_eq(self):
        """重置均衡器"""
        for slider in self.eq_sliders:
            slider.set(0)
        self.status_label.config(text="均衡器已重置")
    
    def reset_tempo(self):
        """重置音频调节"""
        self._updating_sliders = True
        self.beat_slider.set(90)
        self.speed_slider.set(100)
        self.pitch_slider.set(0)
        self._updating_sliders = False
        self.status_label.config(text="音频调节已重置")
        
        song_path = self.get_selected_song_path()
        if song_path:
            if song_path in self.song_configs:
                if 'speed' in self.song_configs[song_path]:
                    del self.song_configs[song_path]['speed']
                if 'pitch' in self.song_configs[song_path]:
                    del self.song_configs[song_path]['pitch']
                self.save_song_configs()
                self.load_playlist(self.current_playlist)
    
    def on_eq_change(self, index, value):
        """均衡器改变事件"""
        pass
    
    def on_beat_change(self, value):
        """节拍改变事件"""
        if self._updating_sliders:
            return
        beat = round(float(value))
        self.status_label.config(text=f"节拍: {round(float(value))}")
    
    def get_selected_song_path(self):
        """获取当前选中歌曲的路径"""
        selection = self.song_table.selection()
        if selection:
            item = selection[0]
            values = self.song_table.item(item, 'values')
            song_index = int(values[0]) - 1
            songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
            if song_index < len(songs):
                return songs[song_index]
        return None
    
    def on_speed_change(self, value):
        """速度改变事件 - 仅更新UI，不立即应用"""
        if self._updating_sliders:
            return
        
        speed = round(float(value))
        song_path = self.get_selected_song_path()
        
        if song_path:
            if song_path not in self.song_configs:
                self.song_configs[song_path] = {}
            self.song_configs[song_path]['speed'] = speed
            self.save_song_configs()
            
            self.status_label.config(text=f"速度: {round(float(value))/100:.1f}x")
            self.update_song_table_row(song_path, 'speed', speed)
            
            if self.player.current_file == song_path and self.player.is_playing:
                self._pending_speed = speed
        else:
            self.status_label.config(text="请先选择一首歌曲")

    def on_speed_slider_release(self, event):
        """速度滑块释放事件 - 应用新速度"""
        if not hasattr(self, '_pending_speed'):
            return
        
        speed = self._pending_speed
        song_path = self.get_selected_song_path()
        
        if song_path and self.player.current_file == song_path and self.player.is_playing:
            current_pos = self.player.get_position()
            self.player._hard_stop()
            self.root.after(50, lambda: self.play_song_by_index(
                self.player.current_index, start_pos=current_pos
            ))
            self._pending_speed = None
            self.status_label.config(text=f"速度已应用: {speed/100:.1f}x")

    def on_pitch_change(self, value):
        """音调改变事件 - 应用于当前选中歌曲，且仅更新UI，不立即应用"""
        if self._updating_sliders:
            return
        
        pitch = round(float(value))
        song_path = self.get_selected_song_path()
        
        if song_path:
            if song_path not in self.song_configs:
                self.song_configs[song_path] = {}
            self.song_configs[song_path]['pitch'] = pitch
            self.save_song_configs()
            self.status_label.config(text=f"音调: {round(float(value))}")
            self.update_song_table_row(song_path, 'pitch', pitch)
            
            if self.player.current_file == song_path and self.player.is_playing:
                self._pending_pitch = pitch
        else:
            self.status_label.config(text="请先选择一首歌曲")

    def on_pitch_slider_release(self, event):
        """音调滑块释放事件 - 应用新音调"""
        if not hasattr(self, '_pending_pitch'):
            return
        
        pitch = self._pending_pitch
        song_path = self.get_selected_song_path()
        
        if song_path and self.player.current_file == song_path and self.player.is_playing:
            current_pos = self.player.get_position()
            self.player._hard_stop()
            self.root.after(50, lambda: self.play_song_by_index(
                self.player.current_index, start_pos=current_pos
            ))
            self._pending_pitch = None
            self.status_label.config(text=f"音调已应用: {pitch}")

    def update_song_table_row(self, song_path, field, value):
        """更新表格中指定歌曲的某个字段"""
        songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
        items = self.song_table.get_children()
        
        for i, item in enumerate(items):
            if i < len(songs) and songs[i] == song_path:
                values = list(self.song_table.item(item, 'values'))
                
                col_map = {
                    'speed': 8,
                    'pitch': 9,
                }
                
                if field in col_map:
                    values[col_map[field]] = str(value)
                    self.song_table.item(item, values=values)
                break

    def update_song_table_optimized(self, songs):
        """优化版更新歌曲表格"""
        # 暂停表格重绘
        self.song_table.configure(displaycolumns=[])
        
        # 批量插入
        rows = []
        for i, song_path in enumerate(songs, 1):
            # ... 构建行数据 ...
            rows.append(row)
        
        # 一次性插入所有行
        for row in rows:
            self.song_table.insert('', 'end', values=row)
        
        # 恢复显示
        self.song_table.configure(displaycolumns=('序号', '播放时间', '歌名', '歌曲时长', 
                                                '起始时间', '播放时长', '停顿时长', 
                                                '音量', '速度', '音调', '灯光'))
        
    # ==================== 音量快捷键 ====================
    
    def decrease_volume(self):
        """减少音量"""
        current = int(self.volume_scale.get())
        new_volume = max(0, current - 5)
        self.volume_scale.set(new_volume)
        self.change_volume(new_volume)
    
    def increase_volume(self):
        """增加音量"""
        current = int(self.volume_scale.get())
        new_volume = min(100, current + 5)
        self.volume_scale.set(new_volume)
        self.change_volume(new_volume)
    
    # ==================== 文件操作功能 ====================
    
    def open_files(self):
        """打开文件对话框"""
        files = filedialog.askopenfilenames(
            title="选择音乐文件",
            filetypes=[
                ("音频文件", "*.mp3 *.wav *.flac *.m4a *.aac *.ogg"),
                ("MP3文件", "*.mp3"),
                ("WAV文件", "*.wav"),
                ("FLAC文件", "*.flac"),
                ("所有文件", "*.*")
            ]
        )
        if files:
            for file in files:
                self.add_song_to_current_playlist(file)
            self.load_playlist(self.current_playlist)
            self.status_label.config(text=f"已添加 {len(files)} 个文件")
    
    def open_folder(self):
        """打开文件夹"""
        folder = filedialog.askdirectory(title="选择音乐文件夹")
        if folder:
            music_files = self.scan_music_files(folder)
            for file in music_files:
                self.add_song_to_current_playlist(file)
            self.load_playlist(self.current_playlist)
            self.load_folder_tree(folder)
            self.status_label.config(text=f"已从文件夹添加 {len(music_files)} 个文件")

    def import_folder_dialog(self):
        """导入文件夹对话框 - 将文件夹内所有音乐添加到当前播放列表"""
        folder = filedialog.askdirectory(title="选择音乐文件夹")
        if folder:
            music_files = self.scan_music_files(folder)
            if music_files:
                for file in music_files:
                    self.add_song_to_current_playlist(file)
                self.load_playlist(self.current_playlist)
                self.status_label.config(text=f"已从文件夹添加 {len(music_files)} 个文件")
            else:
                self.status_label.config(text="该文件夹中没有找到音乐文件")

    def scan_music_files(self, folder):
        """扫描文件夹中的音乐文件"""
        music_extensions = ['.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg']
        music_files = []
        for root, dirs, files in os.walk(folder):
            for file in files:
                if any(file.lower().endswith(ext) for ext in music_extensions):
                    music_files.append(os.path.join(root, file))
        return music_files

    def load_folder_tree_optimized(self, root_folder):
        """优化版加载文件夹树"""
        # 清空现有树
        self.folder_tree.delete(*self.folder_tree.get_children())
        
        # 只加载顶层目录和文件
        self.populate_folder_tree_level(root_folder, max_depth=2)

    def populate_folder_tree_level(self, folder, depth=0, max_depth=2, parent=''):
        """按层级加载文件夹树"""
        if depth > max_depth:
            return
        
        try:
            folder_name = os.path.basename(folder)
            folder_node = self.folder_tree.insert(parent, 'end', text=folder_name, 
                                                values=[folder], open=(depth < 1))
            
            if depth < max_depth:
                for item in os.listdir(folder):
                    item_path = os.path.join(folder, item)
                    if os.path.isdir(item_path):
                        self.populate_folder_tree_level(item_path, depth + 1, max_depth, folder_node)
                    elif item.lower().endswith(('.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg')):
                        self.folder_tree.insert(folder_node, 'end', text=item, values=[item_path])
        except:
            pass

    def load_folder_tree(self, root_folder):
        """加载文件夹树"""
        self.folder_tree.delete(*self.folder_tree.get_children())
        self.populate_folder_tree('', root_folder)
    
    def populate_folder_tree(self, parent, folder):
        """递归填充文件夹树"""
        try:
            folder_name = os.path.basename(folder)
            folder_node = self.folder_tree.insert(parent, 'end', text=folder_name, 
                                                 values=[folder], open=True)
            for item in os.listdir(folder):
                item_path = os.path.join(folder, item)
                if os.path.isdir(item_path):
                    self.populate_folder_tree(folder_node, item_path)
                elif item.lower().endswith(('.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg')):
                    self.folder_tree.insert(folder_node, 'end', text=item, 
                                           values=[item_path])
        except:
            pass
    
    def on_folder_select(self, event):
        """文件夹选择事件"""
        selection = self.folder_tree.selection()
        if selection:
            item = self.folder_tree.item(selection[0])
            if item['values']:
                file_path = item['values'][0]
                if os.path.isfile(file_path):
                    self.add_song_to_current_playlist(file_path)
                    self.load_playlist(self.current_playlist)
    
    def on_folder_double_click(self, event):
        """文件夹双击事件"""
        selection = self.folder_tree.selection()
        if selection:
            item = self.folder_tree.item(selection[0])
            if item['values']:
                file_path = item['values'][0]
                if os.path.isfile(file_path):
                    self.add_song_to_current_playlist(file_path)
                    self.load_playlist(self.current_playlist)
                    songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
                    index = len(songs) - 1
                    self.player.playlist = songs
                    self.player.current_index = index
                    self.play_song_by_index(index)
    
    def open_file_location(self):
        """打开文件所在目录"""
        selection = self.song_table.selection()
        if selection:
            item = selection[0]
            values = self.song_table.item(item, 'values')
            song_index = int(values[0]) - 1
            songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
            if song_index < len(songs):
                file_path = songs[song_index]
                folder = os.path.dirname(file_path)
                if os.path.exists(folder):
                    if os.name == 'nt':
                        os.startfile(folder)
                    else:
                        import subprocess
                        subprocess.run(['xdg-open', folder])
    
    def rename_file(self):
        """重命名文件"""
        selection = self.song_table.selection()
        if selection:
            item = selection[0]
            values = self.song_table.item(item, 'values')
            song_index = int(values[0]) - 1
            songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
            if song_index < len(songs):
                old_path = songs[song_index]
                old_name = os.path.basename(old_path)
                new_name = simpledialog.askstring("重命名", "输入新文件名:", 
                                                 initialvalue=old_name)
                if new_name:
                    new_path = os.path.join(os.path.dirname(old_path), new_name)
                    try:
                        os.rename(old_path, new_path)
                        self.playlist_manager.playlists[self.current_playlist]["songs"][song_index] = new_path
                        self.playlist_manager.save_playlists()
                        self.load_playlist(self.current_playlist)
                        self.status_label.config(text="文件已重命名")
                    except Exception as e:
                        messagebox.showerror("错误", f"重命名失败: {e}")
    
    def delete_file(self):
        """删除文件"""
        selection = self.song_table.selection()
        if selection:
            if messagebox.askyesno("确认删除", "确定要删除选中的文件吗？"):
                item = selection[0]
                values = self.song_table.item(item, 'values')
                song_index = int(values[0]) - 1
                songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
                if song_index < len(songs):
                    file_path = songs[song_index]
                    try:
                        os.remove(file_path)
                        self.playlist_manager.remove_song(self.current_playlist, song_index)
                        self.load_playlist(self.current_playlist)
                        self.status_label.config(text="文件已删除")
                    except Exception as e:
                        messagebox.showerror("错误", f"删除失败: {e}")
    
    def on_drop(self, event):
        """处理拖放文件"""
        files = self.root.tk.splitlist(event.data)
        for file in files:
            if os.path.isfile(file) and file.lower().endswith(('.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg')):
                self.add_song_to_current_playlist(file)
        self.load_playlist(self.current_playlist)
    
    # ==================== 播放控制功能 ====================

    def _start_fade_out_timer(self):
        """开始淡出定时器"""

        # ✅ 如果正在播放前缀音，不触发淡出
        if self._is_playing_prefix:
            print("⚠️ 正在播放前缀音，跳过淡出")
            return
        

        # ✅ 添加防止重复触发的检查
        if hasattr(self, '_fade_out_started') and self._fade_out_started:
            # print("🎚️ 淡出已开始，跳过重复触发")
            return

        # ✅ 检查是否真的是播放快结束了
        current_pos = self._get_current_play_position()
        if current_pos < self.player.current_length - self.player.fade_out_duration - 1:
            print(f"⚠️ 淡出触发过早: 当前位置 {current_pos:.1f}s, 应该在 {self.player.current_length - self.player.fade_out_duration:.1f}s 后")
            return
            
        if self.player.is_playing and not self._playback_completed:
            self._fade_out_started = True  # ✅ 标记淡出已开始
            print(f"🎚️ 开始淡出（剩余 {self.player.fade_out_duration:.1f}s）")
            
            # 获取当前音量
            # current_vol = self.player.volume
            start_volume = self.player.volume  # ✅ 使用不同的变量名
            
            # 启动淡出线程
            def fade_out():
                try:
                    # ✅ 使用局部变量
                    vol = start_volume  # ✅ 使用局部变量
                    steps = int(self.player.fade_out_duration * 10)
                    if steps <= 0:
                        steps = 1
                    
                    vol_step = vol / steps
                    
                    for i in range(steps):
                        if not self.player.is_playing:
                            break
                        vol = vol - vol_step
                        if vol < 0:
                            vol = 0
                        try:
                            pygame.mixer.music.set_volume(vol / 100)
                        except:
                            pass
                        time.sleep(0.1)
                    
                    # 确保音量设置为0
                    try:
                        pygame.mixer.music.set_volume(0)
                    except:
                        pass
                    
                    print(f"🎚️ 淡出完成")
                except Exception as e:
                    print(f"❌ 淡出失败: {e}")
                    import traceback
                    traceback.print_exc()
                    try:
                        pygame.mixer.music.set_volume(0)
                    except:
                        pass
            
            fade_thread = threading.Thread(target=fade_out, daemon=True)
            fade_thread.start()
            print(f"🎚️ 淡出线程已启动")

    def play_song_by_index(self, song_index, start_pos=None):
        """根据索引播放歌曲（应用配置）"""
        # ✅ 使用正在播放的列表ID，而不是当前查看的列表
        playlist_id = self.playing_playlist_id
        if playlist_id is None:
            playlist_id = self.current_playlist
        
        songs = self.playlist_manager.playlists[playlist_id]["songs"]

        if not songs:
            print("⚠️ 播放列表为空")
            self.status_label.config(text="播放列表为空")
            return
        
        if song_index < 0:
            song_index = 0
        elif song_index >= len(songs):
            song_index = len(songs) - 1

        if song_index < 0 or song_index >= len(songs):
            print(f"无效的歌曲索引: {song_index}")
            return
        
        # 取消所有前缀音相关的定时器
        self._cancel_prefix_timers()

        # 取消之前歌曲的播放定时器
        for timer_attr in ['_fade_out_timer_id', '_hard_stop_timer_id', '_check_duration_timer_id']:
            if hasattr(self, timer_attr):
                try:
                    timer_id = getattr(self, timer_attr)
                    if timer_id:
                        self.root.after_cancel(timer_id)
                        print(f"🔧 取消之前的定时器: {timer_attr}")
                except Exception as e:
                    print(f"⚠️ 取消定时器 {timer_attr} 失败: {e}")
                finally:
                    setattr(self, timer_attr, None)
                            
        # 清除前缀音状态
        self._is_playing_prefix = False
        self.current_prefix_file = None
        
        self.player.playlist = songs
        self.player.current_index = song_index
        file_path = songs[song_index]
        config = self.song_configs.get(file_path, {})
        
        # ✅ 关键修复：确保所有变量在使用前都有默认值
        speed = config.get('speed', self.default_settings['speed'])
        pitch = config.get('pitch', self.default_settings['pitch'])
        speed_ratio = speed / 100.0
        
        volume = config.get('volume', self.default_settings['volume'])
        
        fade_in_duration = config.get('fade_in_duration', self.default_settings['fade_in_duration'])
        fade_out_duration = config.get('fade_out_duration', self.default_settings['fade_out_duration'])
        
        pause_duration = config.get('pause_duration', self.default_settings['pause_duration'])
        
        # ✅ 关键修复：将起始时间转换为变速后的时间
        if start_pos is not None:
            actual_start_pos = start_pos
        else:
            # actual_start_pos = config.get('start_time', self.default_settings['start_time'])
            original_start_pos = config.get('start_time', self.default_settings['start_time'])
            # ✅ 如果速度不是100%，需要转换起始时间
            if abs(speed_ratio - 1.0) > 0.01:
                actual_start_pos = original_start_pos / speed_ratio
                print(f"🔄 起始时间转换: 原始{original_start_pos:.2f}s -> 变速后{actual_start_pos:.2f}s")
            else:
                actual_start_pos = original_start_pos
        # ✅ 重要：先预处理音频，获取实际处理后的文件和时长        
        processed_file, is_temp, actual_duration = self.player.prepare_audio(
            file_path, speed_ratio, pitch
        )
        
        if not is_temp and (speed != 100 or pitch != 0):
            print(f"⚠️ 音频处理失败，使用原文件播放（速度/音调将不生效）")
            actual_duration = self.player._get_file_length(file_path)
            # ✅ 如果处理失败，使用原始起始时间
            if start_pos is None:
                actual_start_pos = config.get('start_time', self.default_settings['start_time'])
        
        # ✅ 计算有效播放时长 - 基于实际文件时长和转换后的起始时间
        max_play_duration = max(0, actual_duration - actual_start_pos)
        
        if 'play_duration' in config and config['play_duration'] > 0:
            # ✅ 用户设定的播放时长也需要转换
            if abs(speed_ratio - 1.0) > 0.01:
                play_duration = min(config['play_duration'] / speed_ratio, max_play_duration)
            else:
                play_duration = min(config['play_duration'], max_play_duration)
        else:
            play_duration = max_play_duration
        
        if play_duration < 0:
            play_duration = 0
            print(f"⚠️ 起始时间({actual_start_pos})超过歌曲时长({actual_duration})")
        
        self.player.current_file = file_path
        self.player.current_processed_file = processed_file if is_temp else None
        self.player.current_length = play_duration
        
        self.player.set_volume(volume)
        self.player.fade_in_duration = fade_in_duration
        self.player.fade_out_duration = fade_out_duration
        
        # 更新UI
        self._updating_sliders = True
        self.volume_scale.set(volume)
        self.speed_slider.set(speed)
        self.pitch_slider.set(pitch)
        self._updating_sliders = False

        # ✅ 关键修复：重置播放完成标记
        self._playback_completed = False
        self._is_transitioning = False
        self._fade_out_started = False  # ✅ 重置淡出标记
        self._is_playing_prefix = False
        self.current_prefix_file = None

        # ✅ 记录播放开始时间（用于手动计算位置）
        self._play_start_time = time.time()
        self._play_start_pos = actual_start_pos

        # ✅ 添加：记录正在播放的列表
        self.playing_playlist_id = playlist_id  # ✅ 使用正确的playlist_id
        self.playing_song_index = song_index
        self.playing_song_path = file_path
        
        # print(f"🎵 播放: {os.path.basename(file_path)}")
        # print(f"   ├─ 文件实际时长: {actual_duration:.2f}s")
        # print(f"   ├─ 起始时间: {actual_start_pos:.2f}s")
        # print(f"   ├─ 播放时长: {play_duration:.2f}s")
        # print(f"   ├─ 停顿时长: {pause_duration:.2f}s")
        # print(f"   ├─ 速度: {speed}% ({speed_ratio:.2f}x)")
        # print(f"   ├─ 音调: {pitch}")
        # print(f"   └─ 临时文件: {'是' if is_temp else '否'}")
        
        try:
            if not self.player.load(processed_file):
                self.status_label.config(text=f"加载失败: {os.path.basename(file_path)}")
                return
            
            # 从0音量开始（确保淡入效果）
            pygame.mixer.music.set_volume(0)
            
            # ✅ 记录起始偏移量
            self.player._start_offset = actual_start_pos
            
            with self.player._play_lock:
                if actual_start_pos > 0:
                    pygame.mixer.music.play(start=actual_start_pos)
                    # ✅ 重要：pygame的get_pos()返回从0开始的绝对位置
                    # 所以需要减去起始偏移量
                else:
                    pygame.mixer.music.play()
            
            self.player.is_playing = True
            self.player.is_paused = False

            self.status_label.config(text=f"正在播放: {os.path.basename(file_path)}")
            self.update_status_position()
            self.update_play_times()
            self.show_metadata(file_path)
            self.highlight_playing_song()
            
            self.total_time_label.config(text=self.format_time(play_duration))
            
            # 启动淡入
            self.player._start_fade_in()

            # 设置淡出和停止定时器
            if play_duration > 0:
                # 计算淡出开始时间（从播放开始计算）
                fade_out_start_time = max(0, play_duration - fade_out_duration)
                print(f"⏰ 淡出开始时间: {fade_out_start_time:.1f}s, 硬停止时间: {play_duration:.1f}s")
                
                if fade_out_start_time > 0:
                    # 在淡出开始时间触发淡出
                    self._fade_out_timer_id = self.root.after(
                        int(fade_out_start_time * 1000), 
                        self._start_fade_out_timer
                    )
                else:
                    # 播放时长太短，立即开始淡出
                    self._fade_out_timer_id = self.root.after(100, self._start_fade_out_timer)
                
                # 设置硬停止定时器
                self._hard_stop_timer_id = self.root.after(
                    int(play_duration * 1000), 
                    self._check_play_duration_reached
                )
            
        except Exception as e:
            print(f"❌ 播放失败: {e}")
            import traceback
            traceback.print_exc()
            self.status_label.config(text=f"播放失败: {str(e)[:30]}")

    def _get_current_play_position(self):
        """获取当前播放位置（手动计算）"""
        if hasattr(self, '_play_start_time'):
            elapsed = time.time() - self._play_start_time
            return elapsed
        return 0

    def _check_play_duration_reached(self):
        """检查播放时长是否到达"""
        if self.player.is_playing and not self._playback_completed and not self._is_playing_prefix:
            # ✅ 使用手动计算的位置
            current_pos = self._get_current_play_position()
            
            if current_pos >= self.player.current_length - 0.5:  # 添加0.5秒容差
                print(f"⏱️ 播放时长到达: {current_pos:.1f}s >= {self.player.current_length:.1f}s")
                self._playback_completed = True
                # 立即停止音乐（此时音量已经淡出到0）
                self.player._hard_stop()
                # 触发下一首
                self.trigger_next_song()
            else:
                # 每秒只打印一次日志
                if int(current_pos) != int(getattr(self, '_last_logged_pos', -1)):
                    print(f"⏱️ 当前位置: {current_pos:.1f}s, 目标: {self.player.current_length:.1f}s")
                    self._last_logged_pos = int(current_pos)
                self.root.after(100, self._check_play_duration_reached)

    def _is_current_playlist_playable(self):
        """检查当前列表是否为正在播放的列表"""
        if not self.player.is_playing and not self.player.is_paused:
            return True  # 没有播放任何歌曲，所有列表都可操作
        
        if self.player.current_index < 0:
            return True
        
        # 获取当前播放歌曲
        current_song = None
        if hasattr(self.player, 'current_file'):
            current_song = self.player.current_file
        
        if not current_song:
            return True
        
        # 检查当前播放的歌曲是否在当前列表中
        current_songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
        return current_song in current_songs
    
    def play_music(self):
        """播放音乐"""
        # ✅ 检查是否为正在播放的列表
        if not self._is_current_playlist_playable():
            self.status_label.config(text="⚠️ 当前列表不是正在播放的列表，无法操作")
            return
        
        selection = self.song_table.selection()
        if selection:
            item = selection[0]
            values = self.song_table.item(item, 'values')
            song_index = int(values[0]) - 1
            
            if self._is_transitioning:
                return
            
            if self.player.is_playing or self.player.is_paused:
                self._transition_to_song(song_index)
            else:
                # 使用新的播放方法（支持前缀音）
                self.play_with_prefix(song_index)
                # self.play_song_by_index(song_index)
    
    def _transition_to_song(self, song_index):
        """过渡到指定歌曲（带淡出效果）"""
        if self._is_transitioning:
            return
        
        self._is_transitioning = True

        def do_transition():
            try:
                # ✅ 使用带淡出的停止
                if self.player.is_playing:
                    print(f"🎚️ 开始淡出（{self.player.fade_out_duration}秒）")
                    # 保存当前音量
                    # current_vol = self.player.volume
                    
                    # 启动淡出
                    self.player._fade_out_and_stop()
                    # 等待淡出完成
                    time.sleep(self.player.fade_out_duration + 0.5)  # 增加0.5秒缓冲
            #     else:
            #         self.player._hard_stop()
            #         time.sleep(0.3)  # 未播放时也要稍等
                
            #     self.root.after(0, lambda: self._finish_transition(song_index))
            # except Exception as e:
            #     print(f"过渡失败: {e}")
            #     self._is_transitioning = False
            #     self.root.after(100, lambda: self._finish_transition(song_index))
        
        # threading.Thread(target=do_transition, daemon=True).start()

                    # 确保完全停止
                    self.player._hard_stop()
                    time.sleep(0.2)  # 再等待0.2秒确保完全停止
                elif self.player.is_paused:
                    # 暂停状态直接硬停止
                    self.player._hard_stop()
                    time.sleep(0.2)
                else:
                    # 没有在播放，直接硬停止（清理状态）
                    self.player._hard_stop()
                    time.sleep(0.1)
                
                # 在主线程中完成过渡
                self.root.after(0, lambda: self._finish_transition(song_index))
            except Exception as e:
                print(f"❌ 过渡失败: {e}")
                import traceback
                traceback.print_exc()
                # 出错时也要确保能继续
                self.root.after(100, lambda: self._finish_transition(song_index))
        
        # 在后台线程执行过渡
        threading.Thread(target=do_transition, daemon=True).start()
    
    def _finish_transition(self, song_index):

        """完成过渡，播放新歌曲"""
        print(f"✅ 过渡完成，开始播放歌曲索引: {song_index}")
        
        # 重置过渡状态
        self._is_transitioning = False
        self._playback_completed = False
        self._fade_out_started = False
        
        # 播放新歌曲（使用前缀音播放）
        self.play_with_prefix(song_index)
        # self.play_song_by_index(song_index)

    def pause_music(self):
        """暂停音乐（带滑音）"""
        # ✅ 检查是否为正在播放的列表
        if not self._is_current_playlist_playable():
            self.status_label.config(text="⚠️ 当前列表不是正在播放的列表，无法操作")
            return
        
        if self.player.is_playing:
            self.player.pause()
            self.status_label.config(text="暂停")
        elif self.player.is_paused:
            self.player.resume()
            self.status_label.config(text="继续播放")
    
    def stop_music(self):
        """停止音乐（带滑音）"""
        # ✅ 检查是否为正在播放的列表
        if not self._is_current_playlist_playable():
            self.status_label.config(text="⚠️ 当前列表不是正在播放的列表，无法操作")
            return
        
        self._playback_completed = True  # ✅ 防止自动播放下一首
        
        if self.player.is_playing or self.player.is_paused:
            self.player.stop()
        self.status_label.config(text="停止播放")
        self.progress_bar['value'] = 0
        self.current_time_label.config(text="00:00")
        self.percent_label.config(text="0%")
        self.status_position_label.config(text="0/0")
        self.status_time_display_label.config(text="00:00 / 00:00")

    def on_stop_double_click(self, event):
        """停止按钮双击事件 - 硬停止"""
        self._playback_completed = True  # ✅ 防止自动播放下一首
        
        self.player._hard_stop()
        
        self.status_label.config(text="硬停止")
        self.progress_bar['value'] = 0
        self.current_time_label.config(text="00:00")
        self.percent_label.config(text="0%")
        self.status_position_label.config(text="0/0")
        self.status_time_display_label.config(text="00:00 / 00:00")
        
        self.update_vu_meters(0.0, 0.0)

    def previous_song(self):
        """上一首"""
        if self._is_transitioning:
            return

        # ✅ 检查是否为正在播放的列表
        if not self._is_current_playlist_playable():
            self.status_label.config(text="⚠️ 当前列表不是正在播放的列表，无法操作")
            return

        songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
        if not songs:
            return
        
        self.player.playlist = songs
        if self.player.current_index < 0:
            self.player.current_index = 0
        
        self.player.current_index = (self.player.current_index - 1) % len(songs)

        # ✅ 重置播放完成标记（这两行很重要，不能删除）
        self._playback_completed = False
        self._is_transitioning = False
        
        # ✅ 修复：使用带淡出的过渡
        if self.player.is_playing or self.player.is_paused:
            # 使用过渡方法（带淡出）
            self._transition_to_song(self.player.current_index)
        else:
            # 没有在播放，直接播放
            self.play_with_prefix(self.player.current_index)
            # self.play_song_by_index(self.player.current_index)

    def next_song(self):
        """下一首（自动播放）"""
        print(f"🔄 next_song 被调用, _is_transitioning={self._is_transitioning}")
        if self._is_transitioning:
            print("⏳ 正在过渡中，跳过")
            return

        # ✅ 检查是否为正在播放的列表
        if not self._is_current_playlist_playable():
            self.status_label.config(text="⚠️ 当前列表不是正在播放的列表，无法操作")
            return
        
        # ✅ 使用正在播放的列表ID，而不是当前查看的列表
        playlist_id = self.playing_playlist_id
        if playlist_id is None:
            playlist_id = self.current_playlist
        
        # ✅ 从正确的播放列表取歌
        songs = self.playlist_manager.playlists[playlist_id]["songs"]
        print(f"📋 当前播放列表歌曲数: {len(songs)}")
        if not songs:
            return
        
        self.player.playlist = songs

        if self.player.current_index < 0 or self.player.current_index >= len(songs):
            self.player.current_index = 0

        # 计算下一首索引
        if self.player.play_mode == "random":
            if len(songs) > 1:
                new_index = self.player.current_index
                while new_index == self.player.current_index:
                    new_index = random.randint(0, len(songs) - 1)
                self.player.current_index = new_index
        elif self.player.play_mode == "single_loop":
            if self.player.current_index < 0:
                self.player.current_index = 0
        else:  # sequential
            if self.player.current_index < 0:
                self.player.current_index = 0
            else:
                self.player.current_index = (self.player.current_index + 1) % len(songs)
                print(f"   └─ 切换到索引: {self.player.current_index}, 歌曲: {os.path.basename(songs[self.player.current_index])}")

        # ✅ 重置播放完成标记（这两行很重要，不能删除）
        self._playback_completed = False
        self._is_transitioning = False
        
        # ✅ 修复：使用带淡出的过渡
        if self.player.is_playing or self.player.is_paused:
            # 使用过渡方法（带淡出）
            self._transition_to_song(self.player.current_index)
        else:
            # 没有在播放，直接播放
            self.play_with_prefix(self.player.current_index)
        # 在播放新歌曲后更新状态
        self.update_playlist_status_message()

    def highlight_playing_song(self):
        """高亮当前播放的歌曲"""
        # 只有在当前显示的列表是正在播放的列表时才高亮
        if self.current_playlist != self.playing_playlist_id:
            return
    
        if self.player.current_index >= 0:
            items = self.song_table.get_children()
            if self.player.current_index < len(items):
                self.song_table.selection_set(items[self.player.current_index])
                self.song_table.see(items[self.player.current_index])
    
    def toggle_play_pause(self):
        """切换播放/暂停"""
        if self.player.is_playing:
            self.pause_music()
        elif self.player.is_paused:
            self.pause_music()
        else:
            self.play_music()
    
    def change_volume(self, value):
        """改变音量"""
        if self._updating_sliders:
            return
            
        volume = int(float(value))
        self.player.set_volume(volume)
        
        song_path = self.get_selected_song_path()
        if song_path:
            if song_path not in self.song_configs:
                self.song_configs[song_path] = {}
            self.song_configs[song_path]['volume'] = volume
            self.save_song_configs()

    def update_progress_thread(self):
        """更新进度条线程 - 使用进度检测触发下一首"""
        def update():
            while True:
                try:
                    # 关键修复：如果正在播放前缀音，跳过进度检测
                    # if self._is_playing_prefix:
                    # 关键修复：使用getattr安全访问属性
                    if getattr(self, '_is_playing_prefix', False):
                        time.sleep(0.5)
                        continue
                    
                    if self.player.is_playing and not self.progress_dragging:
                        try:
                            # 使用手动计算的位置
                            current_pos = self._get_current_play_position()
                            total_length = self.player.current_length
                            
                            if total_length > 0 and current_pos >= 0:
                                progress = (current_pos / total_length) * 100
                                progress = max(0, min(100, progress))
                                self.root.after(0, self.update_progress_bar, 
                                            current_pos, total_length, progress)
                                
                                # 关键修复：改进播放完成检测
                                if (not self._playback_completed and 
                                    not getattr(self, '_fade_out_started', False) and
                                    not getattr(self, '_is_playing_prefix', False)):
                                    # 方式1：进度达到99%
                                    if progress >= 99:
                                        self._playback_completed = True
                                        print(f"🎯 播放进度达到 {progress:.1f}%")
                                        # 关键修复：立即停止音乐播放
                                        self.player._hard_stop()
                                        self.root.after(0, self.trigger_next_song)
                                    # 方式2：pygame报告播放结束
                                    elif not pygame.mixer.music.get_busy() and current_pos > 0:
                                        self._playback_completed = True
                                        print("🎯 pygame报告播放结束")
                                        # 关键修复：立即停止音乐播放
                                        self.player._hard_stop()
                                        self.root.after(0, self.trigger_next_song)
                                        
                        except Exception as e:
                            print(f"进度更新错误: {e}")
                    
                    time.sleep(0.5)
                except Exception as e:
                    print(f"进度线程错误: {e}")
                    time.sleep(0.5)
        
        thread = threading.Thread(target=update, daemon=True)
        thread.start()    

    def update_progress_bar(self, current_pos, total_length, progress):
        """更新进度条"""
        if not self.progress_dragging:
            progress = min(100, progress)
            self.progress_bar['value'] = progress
        current_time = self.format_time(current_pos)
        total_time = self.format_time(total_length)
        self.current_time_label.config(text=current_time)
        self.total_time_label.config(text=total_time)
        self.percent_label.config(text=f"{int(progress)}%")
        self.status_time_display_label.config(text=f"{current_time} / {total_time}")

    def format_time(self, seconds):
        """格式化时间为 mm:ss"""
        if seconds < 0:
            seconds = 0
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"
    
    # ==================== 播放列表管理功能 ====================
    
    def load_playlist(self, playlist_num):
        """加载指定播放列表（优化版）"""
        self.current_playlist = playlist_num
        playlist_data = self.playlist_manager.playlists[playlist_num]

        # 取消之前的异步加载任务
        if hasattr(self, '_detail_load_cancelled'):
            self._detail_load_cancelled = True

        # 快速显示歌曲名
        self.update_song_table(playlist_data["songs"])

        # 更新按钮状态
        for id, btn in self.playlist_buttons.items():
            if id == playlist_num:
                btn.config(relief=tk.SUNKEN)
            else:
                btn.config(relief=tk.RAISED)
        
        # ✅ 更新状态提示
        self.update_playlist_status_message()
        self.update_status_position()

        # 异步加载详细信息
        self.load_song_details_async(playlist_data["songs"])

    def update_playlist_status_message(self):
        """更新播放列表状态消息"""
        try:
            # 检查是否正在播放
            if self.playing_playlist_id is None or not self.player.is_playing:
                playlist_name = self.playlist_manager.playlists[self.current_playlist]["name"]
                self.status_label.config(text=f"已切换到: {playlist_name}")
                return
            
            # 获取当前正在播放的歌曲
            current_song = getattr(self.player, 'current_file', None)
            if not current_song:
                playlist_name = self.playlist_manager.playlists[self.current_playlist]["name"]
                self.status_label.config(text=f"已切换到: {playlist_name}")
                return
            
            # 查找包含当前播放歌曲的播放列表
            playing_playlist_id = None
            playing_playlist_name = None
            for pid, pdata in self.playlist_manager.playlists.items():
                if current_song in pdata["songs"]:
                    playing_playlist_id = pid
                    playing_playlist_name = pdata["name"]
                    break
            
            # 更新播放列表ID记录
            self.playing_playlist_id = playing_playlist_id
            
            if playing_playlist_id is None:
                # 找不到播放列表（可能歌曲已被删除）
                playlist_name = self.playlist_manager.playlists[self.current_playlist]["name"]
                self.status_label.config(text=f"已切换到: {playlist_name}")
                return
            
            playing_name = self.playlist_manager.playlists[self.playing_playlist_id]["name"]

            # 检查当前查看的列表是否为正在播放的列表
            if self.current_playlist == self.playing_playlist_id:
                # 当前就在播放列表
                self.status_label.config(text=f"正在播放: {os.path.basename(current_song)}")
            else:
                # 当前查看的不是播放列表
                current_view_name = self.playlist_manager.playlists[self.current_playlist]["name"]
                # self.status_label.config(text=f"⚠️ 正在播放: {os.path.basename(current_song)} (来自 {playing_playlist_name})，当前查看: {current_view_name}")
                self.status_label.config(text=f"正在播放: {playing_playlist_name} → {os.path.basename(current_song)}，当前查看: {current_view_name}")            
        except Exception as e:
            print(f"更新状态消息失败: {e}")

    def update_song_table(self, songs):
        """更新歌曲表格（快速版本）"""
        # 清空表格
        for item in self.song_table.get_children():
            self.song_table.delete(item)
        
        # 快速插入基本信息
        for i, song_path in enumerate(songs, 1):
            song_name = os.path.basename(song_path)
            row = (
                str(i),
                "",
                song_name,
                "--:--",
                "",
                "",
                "",
                "",
                "",
                "",
                ""
            )
            self.song_table.insert('', 'end', values=row)

    def get_audio_duration_seconds_cached(self, file_path):
        """获取音频时长（使用缓存优化）"""
        # 初始化缓存
        if not hasattr(self, '_duration_cache'):
            self._duration_cache = {}
        
        # 检查内存缓存
        if hasattr(self, '_duration_cache') and file_path in self._duration_cache:
            return self._duration_cache[file_path]
        
        # 检查播放器缓存
        if hasattr(self.player, '_length_cache') and file_path in self.player._length_cache:
            duration = self.player._length_cache[file_path]
            self._duration_cache[file_path] = duration
            return duration
        
        # 初始化缓存
        if not hasattr(self, '_duration_cache'):
            self._duration_cache = {}
        
        try:
            # 优先使用 mutagen（更快）
            try:
                audio = mutagen.File(file_path)
                if audio and hasattr(audio, 'info'):
                    duration = audio.info.length
                    self._duration_cache[file_path] = duration
                    if hasattr(self.player, '_length_cache'):
                        self.player._length_cache[file_path] = duration
                    return duration
            except:
                pass
            
            # 回退到 pygame
            sound = pygame.mixer.Sound(file_path)
            duration = sound.get_length()
            self._duration_cache[file_path] = duration
            if hasattr(self.player, '_length_cache'):
                self.player._length_cache[file_path] = duration
            return duration
        except:
            return 0

    def load_song_details_async(self, songs):
        """异步加载歌曲详情"""
        # 取消之前的加载任务
        if hasattr(self, '_detail_load_cancelled'):
            self._detail_load_cancelled = True
        
        self._detail_load_cancelled = False
        current_playlist = self.current_playlist
        
        def load_details():
            try:
                for i, song_path in enumerate(songs):
                    # 检查是否已取消或切换了播放列表
                    if self._detail_load_cancelled or current_playlist != self.current_playlist:
                        return
                    
                    # 获取音频时长（使用缓存）
                    duration_seconds = self.get_audio_duration_seconds_cached(song_path)
                    duration_str = self.format_time(duration_seconds)
                    
                    config = self.song_configs.get(song_path, {})
                    start_time = config.get('start_time', self.default_settings['start_time'])
                    
                    if 'play_duration' in config and config['play_duration'] > 0:
                        play_duration = config['play_duration']
                    else:
                        play_duration = max(0, duration_seconds - start_time)
                    
                    pause_duration = config.get('pause_duration', self.default_settings['pause_duration'])
                    volume = config.get('volume', self.default_settings['volume'])
                    speed = config.get('speed', self.default_settings['speed'])
                    pitch = config.get('pitch', self.default_settings['pitch'])
                    light = config.get('light', '')
                    
                    # 计算播放时间
                    play_time = self.calculate_play_time(i + 1, songs)
                    
                    row = (
                        str(i + 1),
                        play_time,
                        os.path.basename(song_path),
                        duration_str,
                        self.format_time(start_time),
                        self.format_time(play_duration),
                        self.format_time(pause_duration),
                        str(volume),
                        str(speed),
                        str(pitch),
                        light
                    )
                    
                    # 在主线程更新UI
                    self.root.after(0, self.update_song_row, i, row)
                    
                    # 每处理5首歌曲让出CPU
                    if i % 5 == 0:
                        time.sleep(0.01)
                
                # 所有详情加载完成后，更新播放时间
                if not self._detail_load_cancelled and current_playlist == self.current_playlist:
                    self.root.after(0, self.update_play_times)
                
            except Exception as e:
                print(f"异步加载歌曲详情失败: {e}")
        
        # 在后台线程加载
        threading.Thread(target=load_details, daemon=True).start()

    def update_song_row(self, index, row):
        """更新表格中指定行"""
        try:
            items = self.song_table.get_children()
            if index < len(items):
                self.song_table.item(items[index], values=row)
        except Exception as e:
            print(f"更新行失败: {e}")

    def calculate_play_time(self, index, songs):
        """计算预计播放时间（使用播放时长和停顿时长）"""

        now = datetime.datetime.now()
        total_seconds = 0

        # ✅ 核心检查：当前显示的列表必须是正在播放的列表
        # 这个方法已经包含了：
        # 1. 检查 playing_playlist_id 是否为 None
        # 2. 检查 current_playlist 是否等于 playing_playlist_id
        if not self._is_current_playlist_playable():
            return ""        
        
        # ✅ 检查是否有歌曲正在播放
        if not hasattr(self.player, 'current_file') or not self.player.current_file:
            return ""
        
        # 检查是否有歌曲正在播放
        if not self.player.is_playing and not self.player.is_paused:
            return ""
        
        # 检查当前播放的歌曲是否在这个列表中
        if self.player.current_index < 0:
            return ""
        
        # ✅ 获取当前播放的歌曲路径
        current_song_path = self.player.current_file
        
        # 检查当前播放的歌曲是否在这个列表中
        if current_song_path not in songs:
            return ""

        # ✅ 使用"正在播放的列表"而不是"当前显示的列表"
        playing_playlist_id = getattr(self, 'playing_playlist_id', None)
        if playing_playlist_id is None:
            # 如果没有记录，尝试使用current_playlist
            playing_playlist_id = getattr(self, 'current_playlist', None)
        
        if playing_playlist_id is not None:
            try:
                playing_playlist_songs = self.playlist_manager.playlists[playing_playlist_id]["songs"]
                # ✅ 检查传入的列表是否是正在播放的列表
                if playing_playlist_songs != songs:
                    return ""
            except (KeyError, TypeError):
                return ""

        # 找到当前播放歌曲在这个列表中的位置
        current_song_index_in_list = -1
        for i, song in enumerate(songs):
            if song == current_song_path:
                current_song_index_in_list = i
                break
        
        if current_song_index_in_list < 0:
            return ""
        
        # ✅ 计算从当前播放歌曲到目标歌曲的时间
        total_seconds = 0
        
        # 如果目标是当前播放的歌曲
        if index - 1 == current_song_index_in_list:
            return now.strftime("%H:%M")
        
        # 如果目标在当前播放歌曲之后
        if index - 1 > current_song_index_in_list:
            for i in range(current_song_index_in_list, index - 1):
                if i < len(songs):
                    duration = self.get_audio_duration_seconds_cached(songs[i])
                    config = self.song_configs.get(songs[i], {})
                    start_time = config.get('start_time', self.default_settings['start_time'])
                    
                    if 'play_duration' in config and config['play_duration'] > 0:
                        play_duration = config['play_duration']
                    else:
                        play_duration = max(0, duration - start_time)
                    
                    pause_duration = config.get('pause_duration', self.default_settings['pause_duration'])
                    total_seconds += play_duration + pause_duration

                play_time = now + datetime.timedelta(seconds=total_seconds)
                return play_time.strftime("%H:%M")
        else:
            return ""  # 目标在当前播放歌曲之前

    def get_play_duration(self, file_path, config):
        """获取播放时长（统一处理逻辑）"""
        total_duration = self.get_audio_duration_seconds_cached(file_path)
        start_time = config.get('start_time', self.default_settings['start_time'])
        
        if 'play_duration' in config and config['play_duration'] > 0:
            return config['play_duration']
        
        return max(0, total_duration - start_time)

    def update_play_times(self):
        """更新所有歌曲的播放时间"""
        # ✅ 检查是否正在播放
        if not self.player.is_playing and not self.player.is_paused:
            # 清除所有播放时间
            items = self.song_table.get_children()
            for item in items:
                values = list(self.song_table.item(item, 'values'))
                values[1] = ""
                self.song_table.item(item, values=values)
            return
        
        # ✅ 获取当前播放的歌曲
        current_song = getattr(self.player, 'current_file', None)
        if not current_song:
            return
        
        songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
        
        # ✅ 检查当前播放的歌曲是否在这个列表中
        if current_song not in songs:
            # 不是当前播放列表，清除所有播放时间
            items = self.song_table.get_children()
            for item in items:
                values = list(self.song_table.item(item, 'values'))
                values[1] = ""
                self.song_table.item(item, values=values)
            return
        
        # 更新播放时间
        items = self.song_table.get_children()
        for i, item in enumerate(items, 1):
            values = list(self.song_table.item(item, 'values'))
            values[1] = self.calculate_play_time(i, songs)
            self.song_table.item(item, values=values)
    
    def add_song_to_current_playlist(self, song_path):
        """添加歌曲到当前播放列表"""
        result = self.playlist_manager.add_song(self.current_playlist, song_path)
        
        # 如果启用了前缀音，检查并生成新歌曲的前缀音
        if result and self.prefix_enabled:
            filename = os.path.basename(song_path)
            dance_name = extract_dance_name(filename)
            cached = self.prefix_manager.get_cached_prefix(dance_name)
            
            if not cached:
                # 后台生成
                def generate():
                    self.prefix_manager.generate_prefix(dance_name)
                
                threading.Thread(target=generate, daemon=True).start()
        
        return result
        
    def create_new_playlist(self):
        """创建新播放列表"""
        name = simpledialog.askstring("新建播放列表", "输入播放列表名称:")
        if name:
            new_id = self.playlist_manager.create_playlist(name)
            self.update_playlist_buttons()
            self.load_playlist(new_id)
            self.status_label.config(text=f"已创建播放列表: {name}")
    
    def rename_current_playlist(self):
        """重命名当前播放列表"""
        if self.current_playlist == 1:
            messagebox.showwarning("警告", "临时列表不能重命名")
            return
        current_name = self.playlist_manager.playlists[self.current_playlist]["name"]
        new_name = simpledialog.askstring("重命名", "输入新名称:", initialvalue=current_name)
        if new_name:
            self.playlist_manager.rename_playlist(self.current_playlist, new_name)
            self.update_playlist_buttons()
            self.load_playlist(self.current_playlist)
            self.status_label.config(text="播放列表已重命名")
    
    def delete_current_playlist(self):
        """删除当前播放列表"""
        if self.current_playlist == 1:
            messagebox.showwarning("警告", "不能删除默认播放列表")
            return
        
        if messagebox.askyesno("确认删除", "确定要删除当前播放列表吗？"):
            self.playlist_manager.delete_playlist(self.current_playlist)
            self.current_playlist = 1
            self.update_playlist_buttons()
            self.load_playlist(1)
            self.status_label.config(text="播放列表已删除")

    def refresh_playlist(self, playlist_id):
        """覆盖当前列表 - 按当前列表的舞种顺序重新随机生成"""
        playlist_data = self.playlist_manager.playlists.get(playlist_id)
        if not playlist_data:
            return
        
        playlist_name = playlist_data.get("name", "未命名")
        songs = playlist_data.get("songs", [])
        
        if not songs:
            messagebox.showwarning("提示", f"列表 '{playlist_name}' 为空，无法刷新")
            return
        
        # 从当前列表的歌曲中提取舞种顺序
        dance_order = []
        for song_path in songs:
            filename = os.path.basename(song_path)
            dance = self.prefix_manager.get_dance_name(filename)
            if dance:
                dance_order.append(dance)
            else:
                # 如果提取不到舞种，保留文件名作为占位
                dance_order.append("未知")
        
        if not dance_order:
            messagebox.showwarning("提示", 
                f"列表 '{playlist_name}' 中的歌曲无法识别舞种\n"
                "无法执行刷新操作")
            return
        
        # 确认刷新
        if not messagebox.askyesno("确认刷新", 
            f"将替换列表 '{playlist_name}' 中的所有歌曲，是否继续？\n\n"
            f"当前列表有{len(set(dance_order))} 个舞种,共 {len(songs)} 首歌曲，\n"
            f"⚠️ 原歌曲列表将被覆盖，不可恢复！"):
            return
        
        # 检查歌库是否有缓存
        if not hasattr(self, 'generator') or not self.generator.library_cache:
            messagebox.showwarning("提示", "请先在舞种顺序生成器中扫描歌库")
            return
        
        # 使用当前列表的舞种顺序重新生成
        playlist, metadata, warnings = self.generator.generate_playlist(
            dance_order, self.generator.library_cache, ""
        )
        
        if not playlist:
            messagebox.showwarning("提示", "未能生成任何歌曲\n\n" + '\n'.join(warnings[:5]))
            return
        
        # 替换当前列表的歌曲
        self.playlist_manager.playlists[playlist_id]["songs"] = playlist
        
        # 更新批注：追加刷新记录,重新生成完整批注信息（舞种顺序压缩成一行）
        refresh_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # new_remark = remark + f"\n[刷新] {refresh_time} 已重新生成（共 {len(playlist)} 首）"
        # self.playlist_manager.playlists[playlist_id]["remark"] = new_remark
        
        # self.playlist_manager.save_playlists()

        # 从原批注中提取用户备注
        old_remark = playlist_data.get("remark", "")

        # 解析原备注（用户输入的备注）
        user_remark = ""
        for line in old_remark.split('\n'):
            line = line.strip()
            if line.startswith('备注:') and not line.startswith('备注（可编辑）'):
                user_remark = line.replace('备注:', '').strip()
                break
        
        # 构建新的批注信息
        new_remark = f"生成时间: {refresh_time}\n"
        new_remark += f"舞种数: {len(set(dance_order))}\n"
        new_remark += f"舞曲数: {len(playlist)}\n"
        
        # 舞种顺序压缩成一行
        dance_order_str = "舞种顺序：" + "，".join([f"{i+1}.{dance}" for i, dance in enumerate(dance_order)])
        new_remark += dance_order_str + "\n"
        
        if user_remark:
            new_remark += f"备注: {user_remark}\n"
        
        # 追加刷新记录
        new_remark += f"[刷新] {refresh_time} 已重新生成（共 {len(playlist)} 首）"
        
        self.playlist_manager.playlists[playlist_id]["remark"] = new_remark
        self.playlist_manager.save_playlists()
        
        # 如果当前正在查看这个列表，刷新显示
        if self.current_playlist == playlist_id:
            self.load_playlist(playlist_id)
        
        self.status_label.config(text=f"✅ 已重建列表 '{playlist_name}'，共 {len(playlist)} 首歌曲")
        
        # 显示警告详情
        if warnings:
            messagebox.showinfo("刷新完成", 
                f"刷新完成！共 {len(playlist)} 首歌曲\n\n"
                f"有 {len(warnings)} 条警告信息:\n" + '\n'.join(warnings[:10]))


    def _parse_dance_order_from_remark(self, remark):
        """从批注中解析舞种顺序（支持压缩格式）"""
        if not remark:
            return None
        
        # dance_order = []
        # in_dance_section = False
        for line in remark.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # 支持新格式：舞种顺序：1.慢三，2.慢四，3.桑巴，4.斗牛
            if line.startswith('舞种顺序：'):
                # 提取 "1.慢三，2.慢四，3.桑巴，4.斗牛" 部分
                order_part = line.replace('舞种顺序：', '').strip()
                # 按逗号分割
                items = order_part.split('，')
                dance_order = []
                for item in items:
                    item = item.strip()
                    # 去除序号：1.慢三 -> 慢三
                    match = re.match(r'^\s*[\d]+\.\s*(.+)$', item)
                    if match:
                        dance_order.append(match.group(1).strip())
                    else:
                        # 如果没有序号，直接添加
                        dance_order.append(item)
                return dance_order if dance_order else None
            
            # 兼容旧格式（多行）
            if '舞种顺序:' in line and '，' not in line:
                dance_order = []
                in_dance_section = False
                for l in remark.split('\n'):
                    l = l.strip()
                    if not l:
                        continue
                    if '舞种顺序:' in l:
                        in_dance_section = True
                        continue
                    if in_dance_section:
                        match = re.match(r'^\s*[\d]+\.\s*(.+)$', l)
                        if match:
                            dance_order.append(match.group(1).strip())
                        elif l.startswith('[') or l.startswith('---') or l.startswith('生成时间'):
                            break
                return dance_order if dance_order else None
        
        return None

    
    def show_playlist_context_menu(self, event, playlist_id):
        """显示播放列表右键菜单"""
        # 1. 先创建菜单（所有情况都需要）
        context_menu = tk.Menu(self.root, tearoff=0)
        # 2. 重点
        if playlist_id != 1:
            context_menu.add_command(label="查看批注", 
                                    command=lambda: self.view_playlist_remark(playlist_id))
            context_menu.add_command(label="重建列表", 
                                    command=lambda: self.refresh_playlist(playlist_id))
            context_menu.add_separator()
            context_menu.add_command(label="重命名", command=lambda: self.rename_playlist_by_id(playlist_id))
        if playlist_id != 1:
            context_menu.add_command(label="删除", command=lambda: self.delete_playlist_by_id(playlist_id))
        # 3. 这个选项对所有列表都适用
        context_menu.add_separator()
        context_menu.add_command(label="重置该列表所有歌曲配置", 
                                command=lambda: self.reset_playlist_configs(playlist_id))
        # 4. 显示菜单
        context_menu.post(event.x_root, event.y_root)

    def view_playlist_remark(self, playlist_id):
        """查看/编辑播放列表批注 - 合并查看和编辑功能"""
        playlist_data = self.playlist_manager.playlists.get(playlist_id, {})
        full_remark = playlist_data.get("remark", "")
        name = playlist_data.get("name", "未命名")
        
        # 分离备注和其他信息
        lines = full_remark.split('\n') if full_remark else []
        remark_lines = []
        info_lines = []
        # user_remark = ""  # 用户输入的备注
        # in_dance_section = False
        
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue
                
            # 检测元数据行（生成时间、舞种数、舞曲数）
            if (line_stripped.startswith('生成时间:') or 
                line_stripped.startswith('舞种数:') or 
                line_stripped.startswith('舞曲数:')):
                info_lines.append(line_stripped)
                continue
            
            # 舞种顺序 -> 其他信息
            if '舞种顺序' in line_stripped:
                info_lines.append(line_stripped)
                continue

            # 用户备注 -> 备注编辑框（不添加到其他信息）
            if line_stripped.startswith('备注:') and not line_stripped.startswith('备注（可编辑）'):
                user_remark = line_stripped.replace('备注:', '').strip()
                remark_lines.append(user_remark)
                continue
            
            # 刷新记录 -> 其他信息
            if line_stripped.startswith('[刷新]'):
                info_lines.append(line_stripped)
                continue
            
            # 其他行 -> 备注
            remark_lines.append(line_stripped)
        
        current_remark = '\n'.join(remark_lines) if remark_lines else ""
        info_text = '\n'.join(info_lines) if info_lines else "（无其他信息）"
                    
        
        # 创建窗口
        window = tk.Toplevel(self.root)
        window.title(f"批注 - {name}")
        window.geometry("650x520")
        window.transient(self.root)
        window.grab_set()
        window.configure(bg='#1a1a2e')
        
        # 标题
        tk.Label(window, text=f"📋 {name}", 
                font=('微软雅黑', 14, 'bold'),
                bg='#1a1a2e', fg='#3498db').pack(pady=10)
        
        # 备注编辑区
        tk.Label(window, text="📝 备注:", 
                bg='#1a1a2e', fg='#ecf0f1', font=('微软雅黑', 10, 'bold')).pack(anchor='w', padx=20)
        
        remark_entry = tk.Text(window, font=('微软雅黑', 10),
                            bg='#2a2a4e', fg='#ecf0f1', wrap=tk.WORD,
                            height=4, relief=tk.GROOVE, borderwidth=1)
        remark_entry.pack(fill=tk.X, padx=20, pady=(0, 5))
        remark_entry.insert('1.0', current_remark)
        remark_entry.config(state='disabled')  # 默认只读
        
        # 按钮区域（备注和其他信息之间）
        btn_frame = tk.Frame(window, bg='#1a1a2e')
        btn_frame.pack(pady=8)
        
        def enable_edit():
            remark_entry.config(state='normal')
            remark_entry.focus_set()
        
        def save_remark():
            new_remark_text = remark_entry.get('1.0', tk.END).strip()
            
            # 重新构建完整的批注内容
            # 保留其他信息，只替换备注部分
            new_full_remark = ""
            for line in lines:
                if line.strip().startswith('备注:') and not line.strip().startswith('备注（可编辑）'):
                    new_full_remark += f"备注: {new_remark_text}\n"
                else:
                    new_full_remark += line + "\n"
            
            self.playlist_manager.playlists[playlist_id]["remark"] = new_full_remark.strip()
            self.playlist_manager.save_playlists()
            remark_entry.config(state='disabled')
            self.status_label.config(text=f"批注已更新: {name}")
            # window.destroy()
        
        def close_window():
            window.destroy()
        
        tk.Button(btn_frame, text="✏️ 编辑", 
                bg='#f39c12', fg='white', width=10, cursor='hand2',
                command=enable_edit).pack(side=tk.LEFT, padx=5)
        
        tk.Button(btn_frame, text="💾 保存", 
                bg='#2ecc71', fg='white', width=10, cursor='hand2',
                command=save_remark).pack(side=tk.LEFT, padx=5)
        
        tk.Button(btn_frame, text="关闭", 
                bg='#95a5a6', fg='white', width=10, cursor='hand2',
                command=close_window).pack(side=tk.LEFT, padx=5)
        
        # 其他信息（只读）
        tk.Label(window, text="📄 其他信息:", 
                bg='#1a1a2e', fg='#7f8c8d', font=('微软雅黑', 10, 'bold')).pack(anchor='w', padx=20)
        
        info_display = tk.Text(window, font=('微软雅黑', 10),
                            bg='#1a1a2e', fg='#7f8c8d', wrap=tk.WORD,
                            height=10, relief=tk.FLAT)
        info_display.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 10))
        info_display.insert('1.0', info_text)
        info_display.config(state='disabled')  # 只读

    def edit_playlist_remark(self, playlist_id):
        """编辑播放列表批注 - 仅允许编辑备注部分"""
        playlist_data = self.playlist_manager.playlists.get(playlist_id, {})
        full_remark = playlist_data.get("remark", "")
        name = playlist_data.get("name", "未命名")
        
        # 分离备注和其他信息
        lines = full_remark.split('\n') if full_remark else []
        remark_lines = []
        info_lines = []
        in_dance_section = False
        dance_lines = []
        
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue
                
            # 检测舞种顺序开始
            if "舞种顺序:" in line_stripped:
                in_dance_section = True
                dance_lines.append(line_stripped)
                continue
                
            if in_dance_section:
                dance_lines.append(line_stripped)
                continue
            
            # 检测刷新记录（以[刷新]开头）
            if line_stripped.startswith('[刷新]'):
                info_lines.append(line_stripped)
                continue
            
            # 检测元数据行（生成时间、舞种数、歌曲数）
            if (line_stripped.startswith('生成时间:') or 
                line_stripped.startswith('舞种数:') or 
                line_stripped.startswith('歌曲数:') or
                line_stripped.startswith('备注:')):
                info_lines.append(line_stripped)
                continue
            
            # 其他行归为备注
            remark_lines.append(line_stripped)
        
        # 备注内容
        current_remark = '\n'.join(remark_lines) if remark_lines else ""
        
        # 构建其他信息（只读部分）
        info_parts = []
        for line in info_lines:
            if line.startswith('备注:'):
                continue  # 备注单独处理，不放在其他信息里
            info_parts.append(line)
        
        if dance_lines:
            info_parts.extend(dance_lines)
        
        # 添加刷新记录（从原始内容中提取）
        refresh_lines = [l for l in lines if l.strip().startswith('[刷新]')]
        if refresh_lines:
            info_parts.extend(refresh_lines)
        
        info_text = '\n'.join(info_parts) if info_parts else "（无其他信息）"
        
        # 创建编辑窗口
        edit_window = tk.Toplevel(self.root)
        edit_window.title(f"编辑批注 - {name}")
        edit_window.geometry("500x600")
        edit_window.transient(self.root)
        edit_window.grab_set()
        edit_window.configure(bg='#1a1a2e')
        
        # 标题
        tk.Label(edit_window, text=f"✏️ 编辑批注: {name}", 
                font=('微软雅黑', 14, 'bold'),
                bg='#1a1a2e', fg='#3498db').pack(pady=10)
        
        # 备注编辑区（用户可编辑）
        tk.Label(edit_window, text="📝 备注（可编辑）:", 
                bg='#1a1a2e', fg='#ecf0f1', font=('微软雅黑', 10, 'bold')).pack(anchor='w', padx=20)
        
        remark_entry = tk.Text(edit_window, font=('微软雅黑', 10),
                            bg='#2a2a4e', fg='#ecf0f1', wrap=tk.WORD,
                            height=5, relief=tk.GROOVE, borderwidth=1)
        remark_entry.pack(fill=tk.X, padx=20, pady=(0, 10))
        remark_entry.insert('1.0', current_remark)
        
        # 分割线
        separator = tk.Frame(edit_window, bg='#2a2a4e', height=1)
        separator.pack(fill=tk.X, padx=20, pady=5)
        
        # 其他信息（只读，不可编辑）
        tk.Label(edit_window, text="📄 其他信息（只读）:", 
                bg='#1a1a2e', fg='#7f8c8d', font=('微软雅黑', 10, 'bold')).pack(anchor='w', padx=20)
        
        info_display = tk.Text(edit_window, font=('微软雅黑', 10),
                            bg='#1a1a2e', fg='#7f8c8d', wrap=tk.WORD,
                            height=10, relief=tk.FLAT)
        info_display.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 10))
        info_display.insert('1.0', info_text)
        info_display.config(state='disabled')  # 只读
        
        def save_remark():
            new_remark_text = remark_entry.get('1.0', tk.END).strip()
            
            # 重新构建完整的批注内容（只替换备注部分）
            # 格式：备注内容 + 空行 + 其他信息
            if info_text and info_text != "（无其他信息）":
                new_full_remark = new_remark_text + "\n\n" + info_text
            else:
                new_full_remark = new_remark_text
            
            self.playlist_manager.playlists[playlist_id]["remark"] = new_full_remark
            self.playlist_manager.save_playlists()
            edit_window.destroy()
            self.status_label.config(text=f"批注已更新: {name}")
        
        # 底部按钮
        btn_frame = tk.Frame(edit_window, bg='#1a1a2e')
        btn_frame.pack(pady=15)
        
        tk.Button(btn_frame, text="💾 保存", command=save_remark,
                bg='#2ecc71', fg='white', width=10, cursor='hand2').pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="取消", command=edit_window.destroy,
                bg='#95a5a6', fg='white', width=10, cursor='hand2').pack(side=tk.LEFT, padx=5)

    def rename_playlist_by_id(self, playlist_id):
        """根据ID重命名播放列表"""
        current_name = self.playlist_manager.playlists[playlist_id]["name"]
        new_name = simpledialog.askstring("重命名", "输入新名称:", initialvalue=current_name)
        if new_name:
            self.playlist_manager.rename_playlist(playlist_id, new_name)
            self.update_playlist_buttons()
            self.load_playlist(playlist_id)
    
    def delete_playlist_by_id(self, playlist_id):
        """根据ID删除播放列表"""
        if messagebox.askyesno("确认删除", "确定要删除此播放列表吗？"):
            self.playlist_manager.delete_playlist(playlist_id)
            if self.current_playlist == playlist_id:
                self.current_playlist = 1
            self.update_playlist_buttons()
            self.load_playlist(self.current_playlist)
    
    def reset_playlist_configs(self, playlist_id):
        """重置播放列表中所有歌曲的配置"""
        if messagebox.askyesno("确认重置", "确定要重置此播放列表中所有歌曲的配置吗？"):
            songs = self.playlist_manager.playlists[playlist_id]["songs"]
            for song in songs:
                if song in self.song_configs:
                    del self.song_configs[song]
            self.save_song_configs()
            if playlist_id == self.current_playlist:
                self.load_playlist(playlist_id)
            self.status_label.config(text="歌曲配置已重置")
    
    # ==================== 搜索功能 ====================
    
    def search_songs(self):
        """搜索歌曲"""
        search_term = simpledialog.askstring("搜索", "输入搜索关键词:")
        if search_term:
            results = []
            for playlist_id, playlist_data in self.playlist_manager.playlists.items():
                for song in playlist_data["songs"]:
                    if search_term.lower() in os.path.basename(song).lower():
                        results.append((playlist_id, song))
            
            if results:
                self.song_table.delete(*self.song_table.get_children())
                for i, (playlist_id, song) in enumerate(results, 1):
                    song_name = os.path.basename(song)
                    duration_seconds = self.get_audio_duration_seconds_cached(song)
                    duration_str = self.format_time(duration_seconds)
                    
                    config = self.song_configs.get(song, {})
                    start_time = config.get('start_time', self.default_settings['start_time'])
                    play_duration = config.get('play_duration', self.default_settings['play_duration'])
                    pause_duration = config.get('pause_duration', self.default_settings['pause_duration'])
                    volume = config.get('volume', self.default_settings['volume'])
                    speed = config.get('speed', self.default_settings['speed'])
                    pitch = config.get('pitch', self.default_settings['pitch'])
                    light = config.get('light', '')
                    
                    row = (
                        str(i),
                        "",
                        f"[{playlist_id}] {song_name}",
                        duration_str,
                        self.format_time(start_time),
                        self.format_time(play_duration),
                        self.format_time(pause_duration),
                        str(volume),
                        str(speed),
                        str(pitch),
                        light
                    )
                    self.song_table.insert('', 'end', values=row)
                
                self.status_label.config(text=f"找到 {len(results)} 个结果")
            else:
                messagebox.showinfo("搜索", "未找到匹配的歌曲")
    
    # ==================== 灯光控制功能 ====================
    
    def show_light_control(self):
        """显示灯光控制窗口（延迟初始化）"""
        if not self._light_control_initialized:
            # 初始化灯光控制组件
            self._light_control_initialized = True
        # 显示窗口    
        light_window = tk.Toplevel(self.root)
        light_window.title("灯光控制")
        light_window.geometry("400x500")
        
        modes = ["关闭", "常亮", "闪烁", "渐变", "音乐同步"]
        self.light_mode_var = tk.StringVar(value="关闭")
        
        tk.Label(light_window, text="灯光模式:", font=('微软雅黑', 12)).pack(pady=10)
        for mode in modes:
            tk.Radiobutton(light_window, text=mode, variable=self.light_mode_var, 
                          value=mode, font=('微软雅黑', 10)).pack(anchor='w', padx=20)
        
        tk.Label(light_window, text="灯光颜色:", font=('微软雅黑', 12)).pack(pady=10)
        colors_frame = tk.Frame(light_window)
        colors_frame.pack()
        for color in ['红色', '绿色', '蓝色', '白色', '多彩']:
            tk.Button(colors_frame, text=color, width=8, 
                     command=lambda c=color: self.set_light_color(c)).pack(side=tk.LEFT, padx=5)
        
        tk.Label(light_window, text="亮度:", font=('微软雅黑', 12)).pack(pady=10)
        brightness_scale = tk.Scale(light_window, from_=0, to=100, orient=tk.HORIZONTAL)
        brightness_scale.set(50)
        brightness_scale.pack()
    
    def set_light_color(self, color):
        """设置灯光颜色"""
        self.status_label.config(text=f"灯光颜色: {color}")

    # ==================== 添加舞种编辑功能 ====================

    def show_dance_name_editor(self):
        """显示舞种名称编辑器"""
        selection = self.song_table.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一首歌曲")
            return
        
        item = selection[0]
        values = self.song_table.item(item, 'values')
        song_index = int(values[0]) - 1
        songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
        
        if song_index >= len(songs):
            return
        
        song_path = songs[song_index]
        filename = os.path.basename(song_path)
        
        # 获取当前识别的舞种
        current_dance = self.prefix_manager.get_dance_name(filename)
        
        # 创建编辑对话框
        dialog = tk.Toplevel(self.root)
        dialog.title("编辑舞种")
        dialog.geometry("400x300")
        dialog.transient(self.root)
        dialog.grab_set()
        
        tk.Label(dialog, text=f"文件名: {filename}", font=('微软雅黑', 10)).pack(pady=10)
        tk.Label(dialog, text=f"当前识别: {current_dance}", font=('微软雅黑', 10, 'bold')).pack(pady=5)
        
        tk.Label(dialog, text="选择正确的舞种:", font=('微软雅黑', 10)).pack(pady=10)
        
        # 舞种列表
        dance_types = DANCE_TYPES
        
        selected_dance = tk.StringVar(value=current_dance)
        
        # 创建下拉列表
        dance_combo = ttk.Combobox(dialog, textvariable=selected_dance, 
                                values=dance_types, state='readonly')
        dance_combo.pack(pady=10)
    
        def save_dance():
            new_dance = selected_dance.get()
            
            # 保存舞种映射
            self.prefix_manager.set_dance_name(filename, new_dance)
            
            self.status_label.config(text=f"舞种已更新: {filename} -> {new_dance}")
            dialog.destroy()
            
            # 如果启用了前缀音，提示重新生成
            if self.prefix_enabled:
                messagebox.showinfo("提示", f"舞种已更新为 {new_dance}\n前缀音将自动重新生成")
        
        tk.Button(dialog, text="保存", command=save_dance,
                bg='#2ecc71', fg='white', width=15).pack(pady=20)

    # ==================== 新增：更新前缀音播放子菜单 ====================

    def _update_prefix_play_submenu(self):
        """更新前缀音播放子菜单"""
        # 清空现有菜单
        self.prefix_play_submenu.delete(0, tk.END)
        
        self.prefix_play_submenu.add_command(
            label="📁 管理配置",
            command=self.show_prefix_config_manager
        )
        self.prefix_play_submenu.add_separator()

        # 获取所有保存的配置
        configs = self._load_prefix_configs()
        
        if not configs:
            self.prefix_play_submenu.add_command(
                label="（暂无配置，请先创建）",
                state=tk.DISABLED
            )
            return
        
        # 按名称排序
        for name in sorted(configs.keys()):
            self.prefix_play_submenu.add_command(
                label=name,
                command=lambda n=name: self._play_with_prefix_config(n)
            )


        # ✅ 更新"关闭前缀音"菜单项的状态
        self._update_close_prefix_menu()        

    def _load_prefix_configs(self):
        """加载所有保存的前缀音配置"""
        config_file = "prefix_configs.json"
        try:
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载前缀音配置失败: {e}")
        return {}

    def _save_prefix_configs(self, configs):
        """保存所有前缀音配置"""
        config_file = "prefix_configs.json"
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(configs, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存前缀音配置失败: {e}")

    def _play_with_prefix_config(self, config_name):
        """使用指定配置播放前缀音"""
        configs = self._load_prefix_configs()
        config = configs.get(config_name)
        if not config:
            self.status_label.config(text=f"配置 '{config_name}' 不存在")
            return
        
        # 保存当前使用的配置名称
        self._current_prefix_config_name = config_name
        
        # 应用配置到 prefix_audio 模块
        import prefix_audio
        prefix_audio.BGM_VOLUME = config.get('bgm_volume', 0.2)
        prefix_audio.BGM_START_TIME = config.get('bgm_start_time', 0)
        prefix_audio.BGM_TOTAL_DURATION = config.get('bgm_duration', 8)
        prefix_audio.FADE_IN_DUR = config.get('fade_in_duration', 2.0)
        prefix_audio.FADE_OUT_DUR = config.get('fade_out_duration', 2.0)
        prefix_audio.SPEECH_TEXT = config.get('speech_text', '下面请欣赏')
        prefix_audio.SPEECH_POSITION = config.get('speech_position', 'middle')
        prefix_audio.TTS_ENGINE = config.get('tts_engine', 'edge')
        prefix_audio.TTS_VOICE = config.get('tts_voice', 'zh-CN-YunjianNeural')
        
        # ✅ 解析 BGM 文件路径
        bgm_file = config.get('bgm_file')
        speech_text = config.get('speech_text', '')
        
        if bgm_file == "不选择音乐":
            # ✅ 静音模式：无BGM
            prefix_audio.BGM_FILE = None
            self.prefix_enabled = True  # 前缀音功能是开启的，只是没有BGM
            self.status_label.config(text=f"已启用前缀音配置: {config_name}（静音模式）")
            # ✅ 传入 speech_text 判断显示 "无音" 还是 "无文"
            self._update_prefix_status_display(config_name, is_silent=True, speech_text=speech_text)
        else:
            # 有BGM的情况
            if bgm_file == "使用内置BGM":
                # 使用内置BGM（根目录）
                prefix_audio.BGM_FILE = self.prefix_manager.bgm_file
            elif bgm_file == "不选择音乐":
                # 不选择音乐，使用 None
                prefix_audio.BGM_FILE = None
            else:
                # 自定义BGM文件：在 bgm/ 目录中查找
                current_dir = os.path.dirname(os.path.abspath(__file__))
                bgm_dir = os.path.join(current_dir, "bgm")
                test_path = os.path.join(bgm_dir, bgm_file)
                
                # ✅ 如果 bgm/ 目录下存在，使用完整路径
                if os.path.exists(test_path):
                    prefix_audio.BGM_FILE = test_path
                else:
                    prefix_audio.BGM_FILE = self.prefix_manager.bgm_file
                    # 如果不存在，降级到内置BGM
                    self.status_label.config(text=f"⚠️ BGM文件不存在，使用内置BGM")

            # 启用前缀音
            self.prefix_enabled = True
            self.status_label.config(text=f"已启用前缀音配置: {config_name}")
            self._update_prefix_status_display(config_name, is_silent=False, speech_text=speech_text)  # 更新状态栏前缀音显示


        
        # 更新关闭前缀音菜单状态
        self._update_close_prefix_menu()


    def disable_prefix_audio(self):
        """关闭前缀音"""
        self.prefix_enabled = False
        self._current_prefix_config_name = None
        self.status_label.config(text="⏹ 前缀音已关闭")
        print("⏹ 前缀音功能已关闭")

        # ✅ 更新状态栏前缀音显示
        self._update_prefix_status_display()

        # ✅ 更新关闭前缀音菜单状态（变为灰色）
        self._update_close_prefix_menu()
        
        # 取消所有前缀音定时器
        self._cancel_prefix_timers()
        
        # 如果正在播放前缀音，立即停止并播放原曲
        if self._is_playing_prefix and self.player.is_playing:
            self.player._hard_stop()
            self._is_playing_prefix = False
            self.current_prefix_file = None
            # 播放当前选中的歌曲
            if self.player.current_index >= 0:
                self.play_song_by_index(self.player.current_index)

    # ==================== 新增：更新关闭前缀音菜单状态 ====================

    # def _update_close_prefix_menu(self):
    #     """更新关闭前缀音菜单项的状态"""
    #     # 遍历播放菜单找到"关闭前缀音"项
    #     # 由于我们无法直接通过索引访问，使用变量保存菜单项引用
    #     if hasattr(self, '_close_prefix_menu_index'):
    #         try:
    #             # 通过索引更新状态
    #             play_menu = None
    #             # 查找播放菜单
    #             for i in range(self.root.winfo_children()):
    #                 widget = self.root.winfo_children()[i]
    #                 if isinstance(widget, tk.Menu):
    #                     # 检查是否是播放菜单
    #                     if widget.index("end") is not None:
    #                         # 简单判断：查找包含"关闭前缀音"的菜单
    #                         for j in range(widget.index("end") + 1):
    #                             try:
    #                                 label = widget.entrycget(j, "label")
    #                                 if label and "关闭前缀音" in label:
    #                                     if self.prefix_enabled:
    #                                         widget.entryconfig(j, state=tk.NORMAL)
    #                                     else:
    #                                         widget.entryconfig(j, state=tk.DISABLED)
    #                                     break
    #                             except:
    #                                 pass
    #                         break
    #         except Exception as e:
    #             print(f"更新关闭前缀音菜单状态失败: {e}")

    def _update_close_prefix_menu(self):
        """更新关闭前缀音菜单项的状态"""
        try:
            if hasattr(self, '_play_menu') and hasattr(self, '_close_prefix_menu_index'):
                # 计算关闭前缀音菜单项的实际索引
                # 因为我们在添加"关闭前缀音"之前调用了 _update_prefix_play_submenu，
                # 子菜单项会动态变化，所以不能使用固定索引
                # 改为遍历查找
                for j in range(self._play_menu.index("end") + 1):
                    try:
                        label = self._play_menu.entrycget(j, "label")
                        if label and "关闭前缀音" in label:
                            if self.prefix_enabled:
                                self._play_menu.entryconfig(j, state=tk.NORMAL)
                            else:
                                self._play_menu.entryconfig(j, state=tk.DISABLED)
                            return
                    except:
                        pass
        except Exception as e:
            print(f"更新关闭前缀音菜单状态失败: {e}")

    # ==================== 新增：更新前缀音状态显示方法 ====================

    def _update_prefix_status_display(self, config_name=None, is_silent=False, speech_text=""):
        """更新前缀音状态显示
        
        Args:
            config_name: 配置名称，如果为None表示关闭
            is_silent: 是否为静音模式（无BGM）
            speech_text: 语音文本内容
        """
        if self.prefix_enabled and config_name:
            if is_silent:
                # ✅ 检查是否有语音文本
                if speech_text and speech_text.strip():
                    self.status_prefix_label.config(
                        text=f"前缀音: 无音",  # 有文本，无BGM
                        fg="#f39c12"  # 橙色
                    )
                else:
                    self.status_prefix_label.config(
                        text=f"前缀音: 无文",  # 无文本，无BGM
                        fg="#e74c3c"  # 红色
                    )
            else:
                # 正常模式
                self.status_prefix_label.config(
                    text=f"前缀音: 开",
                    fg="#1a6ddb"  # 蓝色
                )
        elif self.prefix_enabled:
            # 已启用但无配置名称（兼容旧逻辑）
            self.status_prefix_label.config(
                text="前缀音: 开",
                fg="#1a6ddb"  # 蓝色
            )
        else:
            # 已关闭
            self.status_prefix_label.config(
                text="前缀音: 关",
                fg='#7f8c8d'  # 灰色
            )

    # ==================== 前缀音功能 ====================

    def _load_prefix_config(self):
        """加载保存的前缀音配置"""
        config_file = "prefix_config.json"
        try:
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self._prefix_config = config
                    
                    # 应用到模块
                    import prefix_audio
                    if 'bgm_volume' in config:
                        prefix_audio.BGM_VOLUME = config['bgm_volume']
                    if 'bgm_start_time' in config:  
                        prefix_audio.BGM_START_TIME = config['bgm_start_time']
                    if 'bgm_duration' in config:
                        prefix_audio.BGM_TOTAL_DURATION = config['bgm_duration']
                    if 'fade_in_duration' in config:
                        prefix_audio.FADE_IN_DUR = config['fade_in_duration']
                    if 'fade_out_duration' in config:
                        prefix_audio.FADE_OUT_DUR = config['fade_out_duration']
                    if 'speech_text' in config:
                        prefix_audio.SPEECH_TEXT = config['speech_text']
                    if 'speech_position' in config:
                        prefix_audio.SPEECH_POSITION = config['speech_position']
                    if 'tts_engine' in config:
                        prefix_audio.TTS_ENGINE = config['tts_engine']
                    if 'tts_voice' in config:
                        prefix_audio.TTS_VOICE = config['tts_voice']
                    self._prefix_config = config
        except Exception as e:
            print(f"加载前缀音配置失败: {e}")
            self._prefix_config = {}

    def show_prefix_config_dialog(self, edit_name=None):
        """显示前缀音配置对话框（弹窗始终加载默认配置,支持编辑模式加载已有配置）"""
        # from prefix_audio import EDGE_VOICES, POSITION_OPTIONS, ENGINE_OPTIONS, DEFAULT_CONFIG

        # 创建前缀音配置对话框
        dialog = tk.Toplevel(self.root)
        dialog.title("前缀音配置" if not edit_name else f"编辑配置: {edit_name}")
        dialog.geometry("450x650+500+100")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg='#1a1a2e')
        
        label_fg = '#ecf0f1'
        entry_bg = '#2a2a4e'
        entry_fg = '#ecf0f1'
        
        # 加载默认配置（不加载当前配置）
        default_config = DEFAULT_CONFIG.copy()
        # default_config = {
        #     'config_name': '',
        #     'bgm_file': '(使用内置BGM)',
        #     'bgm_volume': 0.2,
        #     'bgm_start_time': 0,
        #     'bgm_duration': 8,
        #     'fade_in_duration': 2.0,
        #     'fade_out_duration': 2.0,
        #     'speech_text': '下面请欣赏',
        #     'speech_position': 'middle',
        #     'tts_engine': 'edge',
        #     'tts_voice': 'zh-CN-YunjianNeural'
        # }
        
        # 加载所有配置
        all_configs = self._load_prefix_configs()
        
        # 从默认配置开始
        config_values = default_config.copy()
        is_edit_mode = False
        
        # 如果是编辑模式且有配置，覆盖默认值
        if edit_name and edit_name in all_configs:
            # 加载已有配置的所有参数
            existing = all_configs[edit_name]
            config_values.update(existing)  # ✅ 用已有配置覆盖默认值
            config_values['config_name'] = edit_name
            is_edit_mode = True

        # ✅ 调试：打印加载的配置
        print(f"📝 编辑模式: {is_edit_mode}, 配置名称: {edit_name}")
        print(f"📝 加载的配置: {config_values}")        

        title_label = tk.Label(dialog, text="🎵 前缀音配置", 
                               font=('微软雅黑', 14, 'bold'),
                               bg='#1a1a2e', fg='#3498db')
        title_label.pack(pady=(15, 10))
        
        main_frame = tk.Frame(dialog, bg='#1a1a2e')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)

        vars_dict = {}
        
        # #  修改配置项：label, key, 单位, min_val, max_val, step
        # config_items = [
        #     ("背景音乐音量", 'bgm_volume', "0.1-1.0", 0.1, 1.0, 0.1),
        #     ("背景音乐起始", 'bgm_start_time', "秒", 0, 60, 1),
        #     ("背景音乐时长", 'bgm_duration', "秒", 1, 15, 1),
        #     ("淡入时长", 'fade_in_duration', "秒", 1, 5, 1),
        #     ("淡出时长", 'fade_out_duration', "秒", 1, 5, 1),
        # ]
        
        # for i, (label_text, key, unit, min_val, max_val, step) in enumerate(config_items):
        #     row_frame = tk.Frame(main_frame, bg='#1a1a2e')
        #     row_frame.pack(fill=tk.X, pady=4)
            
        #     # 标签（左对齐，固定宽度）
        #     label = tk.Label(row_frame, text=label_text, width=12, anchor='e',
        #                     bg='#1a1a2e', fg=label_fg, font=('微软雅黑', 9))
        #     label.pack(side=tk.LEFT)
            
        #     #  获取默认值，时长显示为整数
        #     default_val = current_config.get(key, DEFAULT_CONFIG.get(key, 1))
        #     if key == 'bgm_volume':
        #         # 音量保留1位小数
        #         display_val = f"{float(default_val):.1f}"
        #     else:
        #         # 时长显示为整数
        #         display_val = f"{int(float(default_val))}"
            
        #     var = tk.StringVar(value=display_val)
        #     vars_dict[key] = var
            
        #     entry = tk.Entry(row_frame, textvariable=var, width=10,
        #                      bg=entry_bg, fg=entry_fg, insertbackground='white',
        #                      font=('微软雅黑', 9))
        #     entry.pack(side=tk.LEFT, padx=5)
            
        #     # 微调按钮
        #     def make_adjust(key=key, delta=step, min_val=min_val, max_val=max_val):
        #         def adjust():
        #             try:
        #                 val = float(vars_dict[key].get())
        #                 new_val = val + delta
        #                 # 限制范围
        #                 if 'volume' in key:
        #                     new_val = max(0.1, min(1.0, new_val))
        #                     #  音量显示保留小数
        #                     vars_dict[key].set(f"{new_val:.1f}")
        #                 else:
        #                     new_val = max(min_val, min(max_val, new_val))
        #                 # 格式化显示
        #                 # if new_val == int(new_val):
        #                 #     vars_dict[key].set(f"{int(new_val)}")
        #                 # else:
        #                 #     vars_dict[key].set(f"{new_val:.1f}")
        #                     #  时长显示为整数（去除小数点）
        #                     vars_dict[key].set(f"{int(new_val)}")

        #             except:
        #                 pass
        #         return adjust
            
        #     btn_up = tk.Button(row_frame, text="▲", font=('Arial', 8),
        #                     bg='#2a2a4e', fg='#2ecc71', relief=tk.FLAT,
        #                     cursor='hand2', command=make_adjust(delta=step))
        #     btn_up.pack(side=tk.LEFT, padx=1)
            
        #     btn_down = tk.Button(row_frame, text="▼", font=('Arial', 8),
        #                         bg='#2a2a4e', fg='#e74c3c', relief=tk.FLAT,
        #                         cursor='hand2', command=make_adjust(delta=-step))
        #     btn_down.pack(side=tk.LEFT, padx=1)

        #     #  单位标签
        #     if unit:
        #         unit_label = tk.Label(row_frame, text=unit, 
        #                             bg='#1a1a2e', fg='#7f8c8d', 
        #                             font=('微软雅黑', 9))
        #         unit_label.pack(side=tk.LEFT, padx=2)

        # ============================================================
        # 1. 配置名称（必填）
        # ============================================================
        row_frame = tk.Frame(main_frame, bg='#1a1a2e')
        row_frame.pack(fill=tk.X, pady=6)
        
        label = tk.Label(row_frame, text="名称", width=12, anchor='e',
                        bg='#1a1a2e', fg=label_fg, font=('微软雅黑', 9))
        label.pack(side=tk.LEFT)
        
        name_var = tk.StringVar(value=config_values.get('config_name', ''))
        vars_dict['config_name'] = name_var
        
        name_entry = tk.Entry(row_frame, textvariable=name_var, width=22,
                            bg=entry_bg, fg=entry_fg, insertbackground='white',
                            font=('微软雅黑', 9))
        name_entry.pack(side=tk.LEFT, padx=5)
        
        # ============================================================
        # 2. 背景音乐（新增，使用下拉选择）
        # ============================================================
        row_frame = tk.Frame(main_frame, bg='#1a1a2e')
        row_frame.pack(fill=tk.X, pady=6)
        
        label = tk.Label(row_frame, text="音乐", width=12, anchor='e',
                        bg='#1a1a2e', fg=label_fg, font=('微软雅黑', 9))
        label.pack(side=tk.LEFT)
        
        # 获取可用背景音乐
        bgm_files = self.prefix_manager.get_available_bgm_files()
        
        current_bgm = config_values.get('bgm_file', '')
        if current_bgm not in bgm_files:
            current_bgm = ""

        bgm_var = tk.StringVar(value="不选择音乐")  # ✅ 默认选中"不选择音乐"        
        # bgm_var = tk.StringVar(value=current_bgm)
        vars_dict['bgm_file'] = bgm_var
        
        bgm_combo = ttk.Combobox(row_frame, textvariable=bgm_var,
                                values=bgm_files, state='readonly',
                                width=20)
        bgm_combo.pack(side=tk.LEFT, padx=5)

        #  添加分隔线（放在背景音乐和参数之间）
        separator = tk.Frame(main_frame, bg='#2a2a4e', height=1)
        separator.pack(fill=tk.X, pady=8)

        # ============================================================
        # 3. BGM音量（滑块样式，替换原有数值输入）
        # ============================================================
        row_frame = tk.Frame(main_frame, bg='#1a1a2e')
        row_frame.pack(fill=tk.X, pady=2)
        
        label = tk.Label(row_frame, text="音量", width=12, anchor='e',
                        bg='#1a1a2e', fg=label_fg, font=('微软雅黑', 9))
        label.pack(side=tk.LEFT)
        
        volume_var = tk.DoubleVar(value=config_values.get('bgm_volume', 0.2))
        vars_dict['bgm_volume'] = volume_var

        # 滑块宽度设置为与下拉菜单一致（20字符 ≈ 140px）
        volume_scale = tk.Scale(row_frame, from_=0.0, to=1.0, resolution=0.05,
                                orient=tk.HORIZONTAL, length=160,
                                bg='#1a1a2e', fg=label_fg, highlightthickness=0,
                                variable=volume_var, showvalue=1)
        volume_scale.pack(side=tk.LEFT, padx=5)

        # ============================================================
        # 5. BGM起始时间（滑块样式）
        # ============================================================
        row_frame = tk.Frame(main_frame, bg='#1a1a2e')
        row_frame.pack(fill=tk.X, pady=2)
        
        label = tk.Label(row_frame, text="起始", width=12, anchor='e',
                        bg='#1a1a2e', fg=label_fg, font=('微软雅黑', 9))
        label.pack(side=tk.LEFT)
        
        start_time_var = tk.IntVar(value=int(config_values.get('bgm_start_time', 0)))
        vars_dict['bgm_start_time'] = start_time_var
        
        start_time_scale = tk.Scale(row_frame, from_=0, to=60, resolution=1,
                                    orient=tk.HORIZONTAL, length=160,
                                    bg='#1a1a2e', fg=label_fg, highlightthickness=0,
                                    variable=start_time_var, showvalue=1)
        start_time_scale.pack(side=tk.LEFT, padx=5)
        
        tk.Label(row_frame, text="秒", bg='#1a1a2e', fg='#7f8c8d',
                font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=2)
        

        # ============================================================
        # 4. BGM时长（滑块样式）
        # ============================================================
        row_frame = tk.Frame(main_frame, bg='#1a1a2e')
        row_frame.pack(fill=tk.X, pady=2)
        
        label = tk.Label(row_frame, text="时长", width=12, anchor='e',
                        bg='#1a1a2e', fg=label_fg, font=('微软雅黑', 9))
        label.pack(side=tk.LEFT)
        
        duration_var = tk.IntVar(value=int(config_values.get('bgm_duration', 8)))
        vars_dict['bgm_duration'] = duration_var
        
        duration_scale = tk.Scale(row_frame, from_=3, to=15, resolution=1,
                                orient=tk.HORIZONTAL, length=160,
                                bg='#1a1a2e', fg=label_fg, highlightthickness=0,
                                variable=duration_var, showvalue=1)
        duration_scale.pack(side=tk.LEFT, padx=5)
        
        tk.Label(row_frame, text="秒", bg='#1a1a2e', fg='#7f8c8d',
                font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=2)
        
        # ============================================================
        # 6. 淡入时长（滑块样式）
        # ============================================================
        row_frame = tk.Frame(main_frame, bg='#1a1a2e')
        row_frame.pack(fill=tk.X, pady=2)
        
        label = tk.Label(row_frame, text="淡入", width=12, anchor='e',
                        bg='#1a1a2e', fg=label_fg, font=('微软雅黑', 9))
        label.pack(side=tk.LEFT)
        
        fade_in_var = tk.DoubleVar(value=config_values.get('fade_in_duration', 2.0))
        vars_dict['fade_in_duration'] = fade_in_var
        
        fade_in_scale = tk.Scale(row_frame, from_=0.5, to=5.0, resolution=0.5,
                                orient=tk.HORIZONTAL, length=160,
                                bg='#1a1a2e', fg=label_fg, highlightthickness=0,
                                variable=fade_in_var, showvalue=1)
        fade_in_scale.pack(side=tk.LEFT, padx=5)
        
        tk.Label(row_frame, text="秒", bg='#1a1a2e', fg='#7f8c8d',
                font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=2)
        
        # ============================================================
        # 7. 淡出时长（滑块样式）
        # ============================================================
        row_frame = tk.Frame(main_frame, bg='#1a1a2e')
        row_frame.pack(fill=tk.X, pady=2)
        
        label = tk.Label(row_frame, text="淡出", width=12, anchor='e',
                        bg='#1a1a2e', fg=label_fg, font=('微软雅黑', 9))
        label.pack(side=tk.LEFT)
        
        fade_out_var = tk.DoubleVar(value=config_values.get('fade_out_duration', 2.0))
        vars_dict['fade_out_duration'] = fade_out_var
        
        fade_out_scale = tk.Scale(row_frame, from_=0.5, to=5.0, resolution=0.5,
                                orient=tk.HORIZONTAL, length=160,
                                bg='#1a1a2e', fg=label_fg, highlightthickness=0,
                                variable=fade_out_var, showvalue=1)
        fade_out_scale.pack(side=tk.LEFT, padx=5)
        
        tk.Label(row_frame, text="秒", bg='#1a1a2e', fg='#7f8c8d',
                font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=2)

        #  添加分隔线（放在参数和语音设置之间）
        separator = tk.Frame(main_frame, bg='#2a2a4e', height=1)
        separator.pack(fill=tk.X, pady=8)

        #  语音文本输入框（宽度统一为20）
        row_frame = tk.Frame(main_frame, bg='#1a1a2e')
        row_frame.pack(fill=tk.X, pady=6)
        
        tk.Label(row_frame, text="语音文本", width=12, anchor='e',
                 bg='#1a1a2e', fg=label_fg, font=('微软雅黑', 9)).pack(side=tk.LEFT)
        
        default_text = config_values.get('speech_text', '下面请欣赏')
        speech_var = tk.StringVar(value=default_text)
        vars_dict['speech_text'] = speech_var
        
        speech_entry = tk.Entry(row_frame, textvariable=speech_var, width=22,
                                bg=entry_bg, fg=entry_fg, insertbackground='white',
                                font=('微软雅黑', 9))
        speech_entry.pack(side=tk.LEFT, padx=5)
        
        # 提示：+ 舞种名称
        hint_label = tk.Label(row_frame, text="+ 舞种名称", 
                              bg='#1a1a2e', fg='#7f8c8d', font=('微软雅黑', 8))
        hint_label.pack(side=tk.LEFT, padx=5)
        
        # 语音位置下拉菜单 - 使用 grid 布局实现对齐
        row_frame = tk.Frame(main_frame, bg='#1a1a2e')
        row_frame.pack(fill=tk.X, pady=6)

        # 使用 grid 让标签和下拉菜单对齐        
        label_pos = tk.Label(row_frame, text="语音位置", width=12, anchor='e',
                            bg='#1a1a2e', fg=label_fg, font=('微软雅黑', 9))
        label_pos.grid(row=0, column=0, sticky='e', padx=(0, 5))


        # tk.Label(row_frame, text="语音位置:", width=20, anchor='e',
        #          bg='#1a1a2e', fg=label_fg, font=('微软雅黑', 9)).pack(side=tk.LEFT)
        
        pos_var = tk.StringVar(value=config_values.get('speech_position', 'middle'))
        vars_dict['speech_position'] = pos_var
        
        pos_combo = ttk.Combobox(row_frame, textvariable=pos_var,
                                 values=POSITION_OPTIONS, state='readonly',
                                 width=20)
        # pos_combo.pack(side=tk.LEFT, padx=5)
        pos_combo.grid(row=0, column=1, sticky='w', padx=(0, 5))
        
        pos_hint = tk.Label(row_frame, text="开始/中间/结尾", 
                            bg='#1a1a2e', fg='#7f8c8d', font=('微软雅黑', 8))
        # pos_hint.pack(side=tk.LEFT, padx=5)
        pos_hint.grid(row=0, column=2, sticky='w')
        
        # TTS引擎下拉菜单 - 使用 grid 布局
        row_frame = tk.Frame(main_frame, bg='#1a1a2e')
        row_frame.pack(fill=tk.X, pady=6)

        label_engine = tk.Label(row_frame, text="TTS 引擎", width=12, anchor='e',
                                bg='#1a1a2e', fg=label_fg, font=('微软雅黑', 9))
        label_engine.grid(row=0, column=0, sticky='e', padx=(0, 5))


        # tk.Label(row_frame, text="TTS引擎:", width=20, anchor='e',
                #  bg='#1a1a2e', fg=label_fg, font=('微软雅黑', 9)).pack(side=tk.LEFT)
        
        engine_var = tk.StringVar(value=config_values.get('tts_engine', 'edge'))
        vars_dict['tts_engine'] = engine_var
        
        engine_combo = ttk.Combobox(row_frame, textvariable=engine_var,
                                    values=ENGINE_OPTIONS, state='readonly',
                                    width=20)
        # engine_combo.pack(side=tk.LEFT, padx=5)
        engine_combo.grid(row=0, column=1, sticky='w', padx=(0, 5))
        
        engine_hint = tk.Label(row_frame, text="Edge/Google/本地", 
                               bg='#1a1a2e', fg='#7f8c8d', font=('微软雅黑', 8))
        # engine_hint.pack(side=tk.LEFT, padx=5)
        engine_hint.grid(row=0, column=2, sticky='w')
        
        #  语音音色下拉菜单（带"仅Edge可用"提示） - 使用 grid 布局
        row_frame = tk.Frame(main_frame, bg='#1a1a2e')
        row_frame.pack(fill=tk.X, pady=6)
        label_voice = tk.Label(row_frame, text="语音音色", width=12, anchor='e',
                            bg='#1a1a2e', fg=label_fg, font=('微软雅黑', 9))
        label_voice.grid(row=0, column=0, sticky='e', padx=(0, 5))
       
        # tk.Label(row_frame, text="语音音色:", width=20, anchor='e',
        #          bg='#1a1a2e', fg=label_fg, font=('微软雅黑', 9)).pack(side=tk.LEFT)
        
        voice_var = tk.StringVar(value=config_values.get('tts_voice', 'zh-CN-YunjianNeural'))
        vars_dict['tts_voice'] = voice_var
        
        voice_combo = ttk.Combobox(row_frame, textvariable=voice_var,
                                   values=EDGE_VOICES, state='readonly',
                                   width=20)
        # voice_combo.pack(side=tk.LEFT, padx=5)
        voice_combo.grid(row=0, column=1, sticky='w', padx=(0, 5))
        
        #  添加"仅Edge可用"提示标签
        edge_only_label = tk.Label(row_frame, text="仅Edge可用", 
                                bg='#1a1a2e', fg='#f39c12', 
                                font=('微软雅黑', 8, 'bold'))
        # edge_only_label.pack(side=tk.LEFT, padx=5)
        edge_only_label.grid(row=0, column=2, sticky='w')
        
        # 设置列权重，让第二列自动扩展
        # row_frame.grid_columnconfigure(1, weight=1)
        
        # 引擎切换时启用/禁用音色下拉菜单
        def on_engine_change(*args):
            engine = engine_var.get()
            if engine == 'edge':
                voice_combo.config(state='readonly')
                voice_combo.configure(background='white')
                edge_only_label.config(text="Edge可用", fg='#2ecc71')
            else:
                voice_combo.config(state='disabled')
                voice_combo.configure(background='#d3d3d3')
                edge_only_label.config(text="仅Edge可用", fg='#f39c12')
        
        engine_var.trace('w', on_engine_change)
        # 初始化状态
        on_engine_change()
        
        # 预览音色功能
        def preview_voice():
            voice = voice_var.get()
            engine = engine_var.get()
            
            if engine != 'edge':
                messagebox.showinfo("提示", f"当前引擎 ({engine}) 不支持音色预览\n请切换到 Edge 引擎")
                return
            
            try:
                import edge_tts
                import asyncio
                import tempfile
                
                temp_file = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
                temp_path = temp_file.name
                temp_file.close()
                
                text = "魅影提醒您，这是语音音色测试。"
                
                async def test():
                    communicate = edge_tts.Communicate(text, voice)
                    await communicate.save(temp_path)
                
                asyncio.run(test())
                
                if os.path.exists(temp_path):
                    import pygame
                    pygame.mixer.init()
                    pygame.mixer.music.load(temp_path)
                    pygame.mixer.music.play()
                    
                    def cleanup():
                        pygame.mixer.music.stop()
                        time.sleep(0.5)
                        try:
                            os.remove(temp_path)
                        except:
                            pass
                    
                    dialog.after(3000, cleanup)
                    messagebox.showinfo("预览", f"正在播放语音预览:\n音色: {voice}")
                else:
                    messagebox.showerror("预览失败", "无法生成预览语音")
                    
            except Exception as e:
                messagebox.showerror("预览失败", f"语音预览出错: {e}")

        # ============================================================
        # 🆕 预览试听完整前缀音功能
        # ============================================================
        def preview_full_prefix():
            """使用当前对话框参数预览完整前缀音（不保存，不改变全局状态）"""
            try:
                # 收集当前参数
                preview_config = {
                    'bgm_file': bgm_var.get(),
                    'bgm_volume': float(volume_var.get()),
                    'bgm_start_time': int(start_time_var.get()),
                    'bgm_duration': int(duration_var.get()),
                    'fade_in_duration': float(fade_in_var.get()),
                    'fade_out_duration': float(fade_out_var.get()),
                    'speech_text': speech_var.get().strip(),
                    'speech_position': pos_var.get(),
                    'tts_engine': engine_var.get(),
                    'tts_voice': voice_var.get(),
                }

                # 禁用预览按钮，防止重复点击
                preview_full_btn.config(state=tk.DISABLED, text="⏳ 生成中...")

                
                # 显示状态（使用 dialog 中的 status_label）
                status_label.config(text="正在生成预览...", fg='#f39c12')
                dialog.update()

                # ✅ 在后台线程中执行耗时操作
                def generate_preview():
                    try:
                        import prefix_audio
                        import pygame

                        # ✅ 方案3：先停止所有播放
                        try:
                            pygame.mixer.music.stop()
                            pygame.mixer.quit()
                            time.sleep(0.2)
                            pygame.mixer.init()
                        except:
                            pass
                        
                        # ✅ 方案3：清理旧的缓存文件（只清理预览相关的）
                        cache_folder = "prefix_cache"
                        if os.path.exists(cache_folder):
                            for f in os.listdir(cache_folder):
                                if f.startswith("prefix_") and f.endswith(".mp3"):
                                    try:
                                        os.remove(os.path.join(cache_folder, f))
                                        print(f"清理旧缓存: {f}")
                                    except:
                                        pass


                        # 保存当前配置（只保存存在的属性）
                        old_config = {}
                        attrs_to_save = [
                            'BGM_VOLUME', 'BGM_START_TIME', 'BGM_TOTAL_DURATION',
                            'FADE_IN_DUR', 'FADE_OUT_DUR', 'SPEECH_TEXT',
                            'SPEECH_POSITION', 'TTS_ENGINE', 'TTS_VOICE'
                        ]
                        for attr in attrs_to_save:
                            if hasattr(prefix_audio, attr):
                                old_config[attr] = getattr(prefix_audio, attr)
                        
                        # # ✅ BGM_NAMES 是列表，不需要保存和恢复
                        # # 如果用户选择了自定义BGM文件，临时修改 BGM_NAMES
                        # old_bgm_names = None
                        # if hasattr(prefix_audio, 'BGM_NAMES'):
                        #     old_bgm_names = prefix_audio.BGM_NAMES.copy()
                        
                        try:
                            # 应用预览配置
                            prefix_audio.BGM_VOLUME = preview_config['bgm_volume']
                            prefix_audio.BGM_START_TIME = preview_config['bgm_start_time']
                            prefix_audio.BGM_TOTAL_DURATION = preview_config['bgm_duration']
                            prefix_audio.FADE_IN_DUR = preview_config['fade_in_duration']
                            prefix_audio.FADE_OUT_DUR = preview_config['fade_out_duration']
                            prefix_audio.SPEECH_TEXT = preview_config['speech_text']
                            prefix_audio.SPEECH_POSITION = preview_config['speech_position']
                            prefix_audio.TTS_ENGINE = preview_config['tts_engine']
                            prefix_audio.TTS_VOICE = preview_config['tts_voice']
                            
                            # # ✅ 如果用户选择了自定义BGM文件，临时修改 BGM_NAMES
                            # if hasattr(prefix_audio, 'BGM_NAMES'):
                            #     # bgm_file = preview_config['bgm_file']
                            #     # if bgm_file and bgm_file != "(使用内置BGM)":
                            #     #     # 临时替换为自定义文件
                            #     #     prefix_audio.BGM_NAMES = [bgm_file]
                            #     # else:
                            #     #     # 使用默认BGM_NAMES
                            #     #     prefix_audio.BGM_NAMES = old_bgm_names if old_bgm_names else ["bgm.mp3", "bgm.MP3", "背景音乐.mp3", "background.mp3"]

                            #     bgm_file = preview_config['bgm_file']
                            #     bgm_file = None
                            #     bgm_choice = preview_config['bgm_file']
                            #     if bgm_choice and bgm_choice != "(使用内置BGM)":
                            #         bgm_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bgm")
                            #         bgm_file = os.path.join(bgm_dir, bgm_choice)
                            #         if not os.path.exists(bgm_file):
                            #             bgm_file = None  # 文件不存在，使用默认


                            # # 生成预览前缀音（强制重新生成，不读取缓存）
                            # test_dance = "预览测试"
                            # # preview_file = self.prefix_manager.generate_prefix(test_dance, force_regenerate=True)
                            # # 生成预览时传入自定义BGM
                            # preview_file = self.prefix_manager.generate_prefix(
                            #     test_dance, 
                            #     force_regenerate=True,
                            #     bgm_file=bgm_file  # ✅ 传入自定义BGM
                            # )

                            # if preview_file and os.path.exists(preview_file):
                            #     # ✅ 在主线程中播放（使用闭包捕获变量）
                            #     def play_and_cleanup():
                            #         try:
                            #             # 停止当前播放
                            #             try:
                            #                 pygame.mixer.music.stop()
                            #             except:
                            #                 pass

                            # ✅ 构建完整的 BGM 文件路径
                            bgm_file_path = None
                            bgm_choice = preview_config['bgm_file']

                            if bgm_choice == "不选择音乐":
                                # ✅ 不选择音乐 → 静音模式
                                bgm_file_path = "不选择音乐"
                                print("🔇 静音模式：只生成语音")
                            elif bgm_choice == "使用内置BGM":
                                # ✅ 使用内置BGM（根目录）
                                bgm_file_path = "使用内置BGM"
                                print("🎵 使用内置BGM")
                            else:
                                # ✅ 使用 bgm/ 目录中的文件
                                if os.path.exists(bgm_choice):
                                    bgm_file_path = bgm_choice
                                else:
                                    # 在 bgm 目录中查找
                                    current_dir = os.path.dirname(os.path.abspath(__file__))
                                    bgm_dir = os.path.join(current_dir, "bgm")
                                    test_path = os.path.join(bgm_dir, bgm_choice)
                                    if os.path.exists(test_path):
                                        bgm_file_path = test_path
                                    else:
                                        # 如果文件不存在，降级为内置BGM
                                        bgm_file_path = "使用内置BGM"
                                        print(f"⚠️ 文件不存在，使用内置BGM")

                                        # # 在当前目录查找
                                        # test_path = os.path.join(current_dir, bgm_choice)
                                        # if os.path.exists(test_path):
                                        #     bgm_file_path = test_path
                            
                            print(f"选择的BGM文件: {bgm_choice}")
                            print(f"解析后的BGM路径: {bgm_file_path}")
                            
                            # 生成预览前缀音
                            test_dance = "预览测试"
                            preview_file = self.prefix_manager.generate_prefix(
                                test_dance, 
                                force_regenerate=True,
                                bgm_file=bgm_file_path  # ✅ 传递完整路径
                            )
                            
                            if preview_file and os.path.exists(preview_file):
                                def play_and_cleanup():
                                    try:
                                        pygame.mixer.music.stop()


                                        # 播放预览
                                        pygame.mixer.init()
                                        pygame.mixer.music.load(preview_file)
                                        pygame.mixer.music.set_volume(0.8)
                                        pygame.mixer.music.play()
                                        
                                        status_label.config(text="✅ 预览播放中...", fg='#2ecc71')
                                        preview_full_btn.config(state=tk.NORMAL, text="🎧 预览试听")
                                        
                                        # 自动停止和清理
                                        def stop_preview():
                                            try:
                                                if pygame.mixer.music.get_busy():
                                                    pygame.mixer.music.stop()
                                                if os.path.exists(preview_file):
                                                    try:
                                                        os.remove(preview_file)
                                                    except:
                                                        pass
                                                status_label.config(text="预览结束", fg='#7f8c8d')
                                            except:
                                                pass
                                        
                                        stop_delay = int((preview_config['bgm_duration'] + 2) * 1000)
                                        dialog.after(stop_delay, stop_preview)
                                        
                                    except Exception as e:
                                        status_label.config(text=f"❌ 播放失败", fg='#e74c3c')
                                        preview_full_btn.config(state=tk.NORMAL, text="🎧 预览试听")
                                        print(f"播放预览失败: {e}")
                                
                                dialog.after(0, play_and_cleanup)
                                
                            else:
                                dialog.after(0, lambda: status_label.config(text="❌ 预览生成失败", fg='#e74c3c'))
                                dialog.after(0, lambda: preview_full_btn.config(state=tk.NORMAL, text="🎧 预览试听"))
                                dialog.after(0, lambda: messagebox.showerror("预览失败", "无法生成预览前缀音"))
                                
                        finally:
                            # 恢复原始配置
                            for attr, value in old_config.items():
                                if hasattr(prefix_audio, attr):
                                    setattr(prefix_audio, attr, value)
                            
                            # if old_bgm_names is not None and hasattr(prefix_audio, 'BGM_NAMES'):
                            #     prefix_audio.BGM_NAMES = old_bgm_names
                            
                    except Exception as e:
                        dialog.after(0, lambda: status_label.config(text=f"❌ 预览出错", fg='#e74c3c'))
                        dialog.after(0, lambda: preview_full_btn.config(state=tk.NORMAL, text="🎧 预览试听"))
                        dialog.after(0, lambda: messagebox.showerror("预览错误", f"预览失败: {e}"))
                        import traceback
                        traceback.print_exc()
                
                # 启动后台线程
                threading.Thread(target=generate_preview, daemon=True).start()
                
            except Exception as e:
                status_label.config(text=f"❌ 预览出错", fg='#e74c3c')
                preview_full_btn.config(state=tk.NORMAL, text="🎧 预览试听")
                messagebox.showerror("预览错误", f"预览失败: {e}")

            #                     # ✅ 在主线程中播放
            #                     dialog.after(0, lambda: self._play_preview_file(preview_file, preview_config['bgm_duration']))
            #                     dialog.after(0, lambda: status_label.config(text="✅ 预览播放中...", fg='#2ecc71'))
            #                 else:
            #                     dialog.after(0, lambda: status_label.config(text="❌ 预览生成失败", fg='#e74c3c'))
            #                     dialog.after(0, lambda: messagebox.showerror("预览失败", "无法生成预览前缀音"))
                                
            #             finally:
            #                 # 恢复原始配置
            #                 for attr, value in old_config.items():
            #                     if hasattr(prefix_audio, attr):
            #                         setattr(prefix_audio, attr, value)
                            
            #                 # ✅ 恢复 BGM_NAMES
            #                 if old_bgm_names is not None and hasattr(prefix_audio, 'BGM_NAMES'):
            #                     prefix_audio.BGM_NAMES = old_bgm_names
                            
            #                 # ✅ 恢复按钮状态
            #                 dialog.after(0, lambda: preview_full_btn.config(state=tk.NORMAL, text="🎧 预览试听"))
                            
            #         except Exception as e:
            #             dialog.after(0, lambda: status_label.config(text=f"❌ 预览出错", fg='#e74c3c'))
            #             dialog.after(0, lambda: messagebox.showerror("预览错误", f"预览失败: {e}"))
            #             dialog.after(0, lambda: preview_full_btn.config(state=tk.NORMAL, text="🎧 预览试听"))
            #             import traceback
            #             traceback.print_exc()
                
            #     # ✅ 启动后台线程
            #     threading.Thread(target=generate_preview, daemon=True).start()
                
            # except Exception as e:
            #     status_label.config(text=f"❌ 预览出错", fg='#e74c3c')
            #     messagebox.showerror("预览错误", f"预览失败: {e}")
            #     preview_full_btn.config(state=tk.NORMAL, text="🎧 预览试听")

            #     # 使用舞种名称 "测试" 生成预览
            #     test_dance = "测试"
                
            #     # 调用 prefix_manager 生成前缀音（使用预览配置）
            #     import prefix_audio
                
            #     # ✅ 保存当前配置（只保存存在的属性）
            #     old_config = {}
            #     attrs_to_save = [
            #         'BGM_VOLUME', 'BGM_START_TIME', 'BGM_TOTAL_DURATION',
            #         'FADE_IN_DUR', 'FADE_OUT_DUR', 'SPEECH_TEXT',
            #         'SPEECH_POSITION', 'TTS_ENGINE', 'TTS_VOICE'
            #     ]
            #     for attr in attrs_to_save:
            #         if hasattr(prefix_audio, attr):
            #             old_config[attr] = getattr(prefix_audio, attr)
                
            #     # 如果有 BGM_FILE 属性也保存
            #     if hasattr(prefix_audio, 'BGM_FILE'):
            #         old_config['BGM_FILE'] = prefix_audio.BGM_FILE
                
            #     try:
            #         # 应用预览配置
            #         prefix_audio.BGM_FILE = preview_config['bgm_file'] if preview_config['bgm_file'] != "(使用内置BGM)" else ""
            #         prefix_audio.BGM_VOLUME = preview_config['bgm_volume']
            #         prefix_audio.BGM_START_TIME = preview_config['bgm_start_time']
            #         prefix_audio.BGM_TOTAL_DURATION = preview_config['bgm_duration']
            #         prefix_audio.FADE_IN_DUR = preview_config['fade_in_duration']
            #         prefix_audio.FADE_OUT_DUR = preview_config['fade_out_duration']
            #         prefix_audio.SPEECH_TEXT = preview_config['speech_text']
            #         prefix_audio.SPEECH_POSITION = preview_config['speech_position']
            #         prefix_audio.TTS_ENGINE = preview_config['tts_engine']
            #         prefix_audio.TTS_VOICE = preview_config['tts_voice']

            #         if hasattr(prefix_audio, 'BGM_FILE'):
            #             bgm_file = preview_config['bgm_file']
            #             prefix_audio.BGM_FILE = bgm_file if bgm_file and bgm_file != "(使用内置BGM)" else ""
                    
            #         # 生成预览前缀音（强制重新生成，不读取缓存）
            #         preview_file = self.prefix_manager.generate_prefix(test_dance, force_regenerate=True)
                  
            #         if preview_file and os.path.exists(preview_file):
            #             # 播放预览
            #             import pygame
            #             pygame.mixer.init()
            #             pygame.mixer.music.load(preview_file)
            #             pygame.mixer.music.set_volume(0.8)
            #             pygame.mixer.music.play()
                        
            #             status_label.config(text="✅ 预览播放中...", fg='#2ecc71')
                        
            #             # 播放完成后自动停止
            #             def stop_preview():
            #                 try:
            #                     if pygame.mixer.music.get_busy():
            #                         pygame.mixer.music.stop()
            #                     # 清理临时文件
            #                     if os.path.exists(preview_file):
            #                         os.remove(preview_file)
            #                     status_label.config(text="预览结束", fg='#7f8c8d')
            #                 except:
            #                     pass
                        
            #             # 根据时长设置停止定时器
            #             duration = preview_config['bgm_duration'] + 1
            #             dialog.after(int(duration * 1000), stop_preview)
                        
            #             # # 添加手动停止按钮
            #             # stop_btn = tk.Button(button_frame, text="⏹ 停止预览", 
            #             #                     command=stop_preview,
            #             #                     bg='#e74c3c', fg='white', width=12,
            #             #                     font=('微软雅黑', 9), cursor='hand2')
            #             # stop_btn.pack(side=tk.LEFT, padx=5)
            #             # # 保存引用以便清理
            #             # preview_stop_btn = stop_btn
                        
            #         else:
            #             status_label.config(text="❌ 预览生成失败", fg='#e74c3c')
            #             messagebox.showerror("预览失败", "无法生成预览前缀音，请检查配置参数")
                        
            #     finally:
            #         # 恢复原始配置
            #         for attr, value in old_config.items():
            #             if hasattr(prefix_audio, attr):
            #                 setattr(prefix_audio, attr, value)
                            
            # except Exception as e:
            #     # 使用 dialog 中的 status_label
            #     status_label.config(text=f"❌ 预览出错: {str(e)[:20]}", fg='#e74c3c')
            #     messagebox.showerror("预览错误", f"预览失败: {e}")
            #     import traceback
            #     traceback.print_exc()

        # ============================================================
        # 按钮区域
        # ============================================================
        button_frame = tk.Frame(dialog, bg='#1a1a2e')
        button_frame.pack(pady=15)
        
        preview_voice_btn = tk.Button(button_frame, text="🎤 预览音色", 
                                command=preview_voice,
                                bg='#3498db', fg='white', width=12,
                                font=('微软雅黑', 9), cursor='hand2')
        preview_voice_btn.pack(side=tk.LEFT, padx=5)

        # 🆕 完整预览按钮
        preview_full_btn = tk.Button(button_frame, text="🎧 预览试听", 
                                    command=preview_full_prefix,
                                    bg='#f39c12', fg='white', width=12,
                                    font=('微软雅黑', 9, 'bold'), cursor='hand2')
        preview_full_btn.pack(side=tk.LEFT, padx=5)

        def save_config():
            """保存配置（只能另存为新名称）"""
            config_name = name_var.get().strip()
            if not config_name:
                messagebox.showwarning("提示", "请输入配置名称")
                name_entry.focus_set()
                return
            
            try:
                # 获取所有配置
                all_configs = self._load_prefix_configs()
                
                # 检查同名配置
                if config_name in all_configs:
                    # 如果是编辑模式且名称相同，允许保存（覆盖）
                    if is_edit_mode and config_name == edit_name:
                        # 编辑模式保存同名配置，直接覆盖
                        pass
                    else:
                        # 不同名称或非编辑模式，询问是否覆盖
                        if not messagebox.askyesno("确认覆盖", 
                            f"配置 '{config_name}' 已存在，是否覆盖替换？"):
                            return
                
                # 构建新配置
                new_config = {}
                for key, var in vars_dict.items():
                    if key == 'config_name':
                        continue
                    val = var.get()
                    # if key in ['bgm_start_time', 'bgm_duration', 'fade_in_duration', 'fade_out_duration']:
                    if key in ['bgm_start_time', 'bgm_duration']:
                        new_config[key] = int(float(val))
                    elif key in ['fade_in_duration', 'fade_out_duration']:

                        new_config[key] = float(val)
                    elif key == 'bgm_volume':
                        new_config[key] = max(0.05, min(1.0, float(val)))
                    else:
                        new_config[key] = val
                
                # self._prefix_config = new_config                
                # import prefix_audio
                # prefix_audio.BGM_VOLUME = new_config['bgm_volume']
                # prefix_audio.BGM_START_TIME = new_config['bgm_start_time']
                # prefix_audio.BGM_TOTAL_DURATION = new_config['bgm_duration']
                # prefix_audio.FADE_IN_DUR = new_config['fade_in_duration']
                # prefix_audio.FADE_OUT_DUR = new_config['fade_out_duration']
                # prefix_audio.SPEECH_TEXT = new_config['speech_text']
                # prefix_audio.SPEECH_POSITION = new_config['speech_position']
                # prefix_audio.TTS_ENGINE = new_config['tts_engine']
                # prefix_audio.TTS_VOICE = new_config['tts_voice']
                
                # config_file = "prefix_config.json"
                # try:
                #     with open(config_file, 'w', encoding='utf-8') as f:
                #         json.dump(new_config, f, ensure_ascii=False, indent=2)
                # except:
                #     pass

                # 保存配置
                all_configs[config_name] = new_config
                self._save_prefix_configs(all_configs)
                
                # 更新前缀音播放子菜单
                self._update_prefix_play_submenu()

                # ✅ 更新"关闭前缀音"菜单状态（如果有配置，启用关闭菜单）
                # 注意：这里只是更新菜单状态，不改变前缀音启用状态
                self._update_close_prefix_menu()
                
                # ✅ 注意：保存配置不自动启用前缀音，所以状态栏显示不变
                # 但如果用户想启用，可以点击子菜单中的配置名称
                
                self.status_label.config(text=f"✅ 前缀音配置已保存: {config_name}")

                dialog.destroy()
                
                # #  关键修复：保存配置后，标记为已启用
                # self.prefix_enabled = True

                # #  显示状态
                # self.status_label.config(text="前缀音已启用，正在生成缓存...")
                # print("✅ 配置已保存，前缀音已启用")
                        
                
                # self.root.after(500, self.auto_generate_missing_prefixes)
                # 注意：auto_generate_missing_prefixes 会在 toggle_prefix_audio 中调用
                # 这里不重复调用，避免重复生成                        
            except ValueError as e:
                messagebox.showerror("错误", f"请输入有效的数字: {e}")
        
        def cancel_config():
            # 停止任何正在播放的预览
            try:
                import pygame
                pygame.mixer.music.stop()
            except:
                pass
            dialog.destroy()
        
        # 保存和取消按钮
        save_btn = tk.Button(button_frame, text="💾 保存配置", 
                            command=save_config,
                            bg='#2ecc71', fg='white', width=12,
                            font=('微软雅黑', 9), cursor='hand2')
        save_btn.pack(side=tk.LEFT, padx=5)
        
        cancel_btn = tk.Button(button_frame, text="❌ 取消", 
                               command=cancel_config,
                               bg='#95a5a6', fg='white', width=8,
                               font=('微软雅黑', 9), cursor='hand2')
        cancel_btn.pack(side=tk.LEFT, padx=5)
        
        # 状态标签
        status_label = tk.Label(dialog, text="💡 调整参数后点击「预览试听」体验效果", 
                                bg='#1a1a2e', fg='#7f8c8d', font=('微软雅黑', 9))
        status_label.pack(pady=(0, 10))

        # 底部提示
        tip_label = tk.Label(dialog, text="提示：修改参数后请输入新名称保存，不会影响默认配置", 
                             bg='#1a1a2e', fg='#f39c12', font=('微软雅黑', 9))
        tip_label.pack(pady=(0, 10))

        dialog.bind('<Return>', lambda e: save_config())
        dialog.bind('<Escape>', lambda e: cancel_config())

    # ==================== 新增：配置管理窗口 ====================

    def show_prefix_config_manager(self):
        """显示前缀音配置管理窗口"""
        configs = self._load_prefix_configs()
        
        if not configs:
            messagebox.showinfo("提示", "暂无保存的配置")
            return
        
        manager_window = tk.Toplevel(self.root)
        manager_window.title("前缀音配置管理")
        manager_window.geometry("500x500")
        manager_window.transient(self.root)
        manager_window.grab_set()
        manager_window.configure(bg='#1a1a2e')
        
        tk.Label(manager_window, text="📁 前缀音配置管理",
                font=('微软雅黑', 14, 'bold'),
                bg='#1a1a2e', fg='#3498db').pack(pady=10)
        
        # 配置列表
        list_frame = tk.Frame(manager_window, bg='#1a1a2e')
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        columns = ('名称', '引擎', '音色', '时长')
        tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=10)
        
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=80, anchor='center')
        tree.column('名称', width=120)
        tree.column('音色', width=150)
        
        scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        for name, config in configs.items():
            tree.insert('', 'end', values=(
                name,
                config.get('tts_engine', 'edge'),
                config.get('tts_voice', '默认')[:20],
                f"{config.get('bgm_duration', 8)}s"
            ))
        
        # 双击编辑
        def on_tree_double_click(event):
            selection = tree.selection()
            if not selection:
                return
            item = tree.item(selection[0])
            name = item['values'][0]
            manager_window.destroy()
            # ✅ 编辑时传入配置名称，加载已有配置
            self.show_prefix_config_dialog(edit_name=name)
        
        tree.bind('<Double-1>', on_tree_double_click)
        
        # 操作按钮
        btn_frame = tk.Frame(manager_window, bg='#1a1a2e')
        btn_frame.pack(pady=15)
        
        def on_edit():
            selection = tree.selection()
            if not selection:
                messagebox.showinfo("提示", "请先选择一个配置")
                return
            item = tree.item(selection[0])
            name = item['values'][0]
            manager_window.destroy()
            # ✅ 编辑时传入配置名称，加载已有配置
            self.show_prefix_config_dialog(edit_name=name)
        
        def on_delete():
            selection = tree.selection()
            if not selection:
                messagebox.showinfo("提示", "请先选择一个配置")
                return
            item = tree.item(selection[0])
            name = item['values'][0]
            
            if messagebox.askyesno("确认删除", f"确定要删除配置 '{name}' 吗？"):
                configs = self._load_prefix_configs()
                if name in configs:
                    del configs[name]
                    self._save_prefix_configs(configs)
                    self._update_prefix_play_submenu()
                    tree.delete(selection[0])
                    self.status_label.config(text=f"已删除配置: {name}")
        
        def on_use():
            selection = tree.selection()
            if not selection:
                messagebox.showinfo("提示", "请先选择一个配置")
                return
            item = tree.item(selection[0])
            name = item['values'][0]
            manager_window.destroy()
            self._play_with_prefix_config(name)
        
        tk.Button(btn_frame, text="▶使用", command=on_use,
                bg='#2ecc71', fg='white', width=10, cursor='hand2').pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="✏️编辑", command=on_edit,
                bg='#3498db', fg='white', width=10, cursor='hand2').pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="🗑️删除", command=on_delete,
                bg='#e74c3c', fg='white', width=10, cursor='hand2').pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="❌关闭", command=manager_window.destroy,
                bg='#95a5a6', fg='white', width=10, cursor='hand2').pack(side=tk.LEFT, padx=5)


    # def toggle_prefix_audio(self):
    #     """切换前缀音功能"""
    #     #  关键修复：获取当前实际状态（点击前的状态）
    #     # 由于 checkbutton 的 command 在状态变化后执行，我们需要用 self.prefix_enabled 来判断
    #     # current_state = self.prefix_enabled
        
    #     if not self.prefix_enabled:
    #         # 从关闭→启用：显示配置对话框
    #         # 注意：启用状态会在保存配置时才设置，取消则不启用
    #         self.show_prefix_config_dialog()
    #         # 对话框关闭后，检查是否真的启用了（由 save_config 或 cancel_config 设置）
    #         if self.prefix_enabled:
    #             # self.status_label.config(text="前缀音已启用，正在检查缓存...")
    #             # ✅ 状态栏已经在 save_config 中设置了，这里只需要生成缓存

    #             print("✅ 前缀音功能已启用")
    #             # 启动自动检查并生成缺失的前缀音缓存（会更新状态栏）
    #             self.auto_generate_missing_prefixes()
    #         else:
    #             # 用户取消了，确保复选框状态正确
    #             #  状态栏已经在 cancel_config 中设置了，不重复设置

    #             # self.status_label.config(text="已取消启用")
    #             print("❌ 用户取消启用前缀音")
    #     else:
    #         # 从启用→关闭：直接禁用，不弹窗
    #         self.prefix_enabled = False
    #         self.status_label.config(text="前缀音已禁用")
    #         print("❌ 前缀音功能已禁用")
            
    #         # 取消所有前缀音定时器
    #         self._cancel_prefix_timers()
            
    #         # 如果正在播放前缀音，立即停止并播放原曲
    #         if self._is_playing_prefix and self.player.is_playing:
    #             self.player._hard_stop()
    #             self._is_playing_prefix = False
    #             self.current_prefix_file = None
    #             # 播放当前选中的歌曲
    #             if self.player.current_index >= 0:
    #                 self.play_song_by_index(self.player.current_index)

    # def auto_generate_missing_prefixes(self):
    #     """自动生成缺失的前缀音（后台静默进行）"""
    #     def check_and_generate():
    #         try:
    #             # 收集所有需要的前缀音
    #             dance_names = set()
    #             for playlist_data in self.playlist_manager.playlists.values():
    #                 for song_path in playlist_data["songs"]:
    #                     filename = os.path.basename(song_path)
    #                     dance_name = extract_dance_name(filename)
    #                     dance_names.add(dance_name)
                
    #             # 检查哪些需要生成
    #             missing_count = 0
    #             for dance_name in dance_names:
    #                 cached = self.prefix_manager.get_cached_prefix(dance_name)
    #                 if not cached:
    #                     missing_count += 1
                
    #             if missing_count == 0:
    #                 #  修复：直接显示启用成功
    #                 self.root.after(0, lambda: self.status_label.config(
    #                     text="前缀音已启用，所有缓存就绪"
    #                 ))
    #                 print("✅ 前缀音已启用，所有缓存就绪")
    #                 return
                
    #             # 更新状态
    #             self.root.after(0, lambda: self.status_label.config(
    #                 text=f"正在生成 {missing_count} 个前缀音..."
    #             ))
                
    #             # 逐个生成
    #             generated = 0
    #             for dance_name in dance_names:
    #                 cached = self.prefix_manager.get_cached_prefix(dance_name)
    #                 if not cached:
    #                     print(f"🔄 生成前缀音: {dance_name}")
    #                     result = self.prefix_manager.generate_prefix(dance_name)
    #                     if result:
    #                         generated += 1
    #                         self.root.after(0, lambda d=dance_name, g=generated, m=missing_count: 
    #                                     self.status_label.config(
    #                                         text=f"前缀音生成中: {g}/{m} - {d}"
    #                                     ))
                
    #             #  修复：生成完成后显示成功
    #             self.root.after(0, lambda: self.status_label.config(
    #                 text=f"前缀音已启用，新生成 {generated} 个"
    #             ))
    #             print(f"✅ 前缀音自动生成完成: {generated}/{missing_count}")
                
    #         except Exception as e:
    #             print(f"❌ 自动生成前缀音失败: {e}")
    #             self.root.after(0, lambda: self.status_label.config(
    #                 text="前缀音已启用（部分生成失败）"
    #             ))
        
    #     # 在后台线程中执行
    #     threading.Thread(target=check_and_generate, daemon=True).start()

    # def batch_generate_prefixes(self):
    #     """批量预生成前缀音"""
    #     # 收集所有舞种名称
    #     dance_names = set()
    #     for playlist_data in self.playlist_manager.playlists.values():
    #         for song_path in playlist_data["songs"]:
    #             filename = os.path.basename(song_path)
    #             dance_name = extract_dance_name(filename)
    #             dance_names.add(dance_name)
        
    #     if not dance_names:
    #         messagebox.showinfo("提示", "播放列表为空，无法生成前缀音")
    #         return
        
    #     # 创建进度窗口
    #     progress_window = tk.Toplevel(self.root)
    #     progress_window.title("批量生成前缀音")
    #     progress_window.geometry("400x200")
    #     progress_window.transient(self.root)
    #     progress_window.grab_set()
        
    #     tk.Label(progress_window, text="正在生成前缀音...", 
    #             font=('微软雅黑', 12)).pack(pady=10)
        
    #     progress_bar = ttk.Progressbar(progress_window, length=300, mode='determinate')
    #     progress_bar.pack(pady=10)
        
    #     status_label = tk.Label(progress_window, text="准备开始...", 
    #                         font=('微软雅黑', 10))
    #     status_label.pack(pady=5)
        
    #     detail_text = tk.Text(progress_window, height=5, width=50)
    #     detail_text.pack(pady=5, padx=10)
        
    #     dance_names_list = list(dance_names)
    #     total = len(dance_names_list)
        
    #     def update_progress(current, total_count, dance_name, result):
    #         progress_bar['value'] = (current / total_count) * 100
    #         status_label.config(text=f"进度: {current}/{total_count}")
            
    #         if result:
    #             detail_text.insert(tk.END, f"✅ {dance_name}: 成功\n")
    #         else:
    #             detail_text.insert(tk.END, f"❌ {dance_name}: 失败\n")
            
    #         detail_text.see(tk.END)
    #         progress_window.update()
        
    #     def generate_in_thread():
    #         try:
    #             for i, dance_name in enumerate(dance_names_list):
    #                 result = self.prefix_manager.generate_prefix(dance_name)
    #                 self.root.after(0, update_progress, i + 1, total, dance_name, result)
                
    #             self.root.after(0, lambda: status_label.config(text="生成完成！"))
    #             self.root.after(0, lambda: messagebox.showinfo("完成", "前缀音生成完成！"))
    #         except Exception as e:
    #             self.root.after(0, lambda: messagebox.showerror("错误", f"生成失败: {e}"))
        
    #     threading.Thread(target=generate_in_thread, daemon=True).start()

    def get_prefix_file_for_song(self, song_path):
        """获取歌曲对应的前缀音文件"""
        if not self.prefix_enabled:
            return None
        
        filename = os.path.basename(song_path)
        dance_name = extract_dance_name(filename)
        
        # 检查缓存
        cached = self.prefix_manager.get_cached_prefix(dance_name)
        if cached:
            return cached
        
        # 生成新的前缀音
        print(f"🔄 生成前缀音: {dance_name}")
        return self.prefix_manager.generate_prefix(dance_name)
    
    def play_with_prefix(self, song_index, start_pos=None):
        """播放歌曲（带前缀音）"""
        if not self.prefix_enabled:
            # 未启用前缀音，直接播放
            self.play_song_by_index(song_index, start_pos)
            return

        # ✅ 使用正在播放的列表ID，而不是当前查看的列表
        playlist_id = self.playing_playlist_id
        if playlist_id is None:
            playlist_id = self.current_playlist
        
        # ✅ 临时列表禁用前缀音
        if playlist_id == 1:
            print("📋 临时列表禁用前缀音，直接播放")
            self.play_song_by_index(song_index, start_pos)
            return

        songs = self.playlist_manager.playlists[playlist_id]["songs"]
        if song_index < 0 or song_index >= len(songs):
            return
        
        song_path = songs[song_index]
        filename = os.path.basename(song_path)
        # dance_name = extract_dance_name(filename)
        # 使用改进的舞种识别（包含手动映射）
        dance_name = self.prefix_manager.get_dance_name(filename)
                
        # 取消所有之前的前缀音相关定时器
        self._cancel_prefix_timers()
        
        # 重置前缀音状态
        self._is_playing_prefix = False
        self.current_prefix_file = None
        
        # 检查缓存
        prefix_file = self.prefix_manager.get_cached_prefix(dance_name)
        
        if not prefix_file or not os.path.exists(prefix_file):
            # 缓存中没有或文件不存在，显示正在生成
            self.status_label.config(text=f"正在生成前缀音: {dance_name}...")
            print(f"🔄 生成前缀音: {dance_name}")
            
            # 在后台生成
            def generate_and_play():
                try:
                    generated_file = self.prefix_manager.generate_prefix(dance_name)
                    if generated_file and os.path.exists(generated_file):
                        self.root.after(0, lambda: self._start_prefix_playback(
                            generated_file, song_index, start_pos
                        ))
                    else:
                        # 生成失败，直接播放原曲
                        print(f"⚠️ 前缀音生成失败，直接播放原曲")
                        self.root.after(0, lambda: self.play_song_by_index(song_index, start_pos))
                except Exception as e:
                    print(f"❌ 前缀音生成异常: {e}")
                    import traceback
                    traceback.print_exc()
                    self.root.after(0, lambda: self.play_song_by_index(song_index, start_pos))
            
            threading.Thread(target=generate_and_play, daemon=True).start()
        else:
            # 有缓存，直接播放
            self._start_prefix_playback(prefix_file, song_index, start_pos)

    def _start_prefix_playback(self, prefix_file, song_index, start_pos):
        """开始播放前缀音（延迟后播放）"""
        print(f"▶️ 准备播放前缀音")
        self.status_label.config(text="准备播放前缀音...")
        
        # 延迟1秒后播放
        self._prefix_delay_timer = self.root.after(
            1000,
            lambda: self._play_prefix_audio(prefix_file, song_index, start_pos)
        )

    def _play_prefix_audio(self, prefix_file, song_index, start_pos):
        """实际播放前缀音"""
        try:
            # 取消上一首歌曲的播放定时器
            for timer_attr in ['_fade_out_timer_id', '_hard_stop_timer_id', '_check_duration_timer_id']:
                if hasattr(self, timer_attr):
                    try:
                        timer_id = getattr(self, timer_attr)
                        if timer_id:
                            self.root.after_cancel(timer_id)
                            print(f"🔧 取消之前的定时器: {timer_attr}")
                    except Exception as e:
                        print(f"⚠️ 取消定时器 {timer_attr} 失败: {e}")
                    finally:
                        setattr(self, timer_attr, None)

            # 硬停止当前播放
            self.player._hard_stop()
            time.sleep(0.05)
            
            # 加载并播放前缀音
            pygame.mixer.music.load(prefix_file)
            pygame.mixer.music.set_volume(0)  # 从0开始，由淡入控制
            pygame.mixer.music.play()
            
            # 关键：设置前缀音播放状态
            self.player.is_playing = True
            self.player.is_paused = False
            self._is_playing_prefix = True  # 标记正在播放前缀音
            self.current_prefix_file = prefix_file
            
            # 更新当前歌曲索引和高亮
            self.player.current_index = song_index
            self.player.playlist = self.playlist_manager.playlists[self.current_playlist]["songs"]
            
            # 设置当前播放长度为前缀音时长（从配置读取）
            import prefix_audio
            prefix_duration = prefix_audio.BGM_TOTAL_DURATION
            self.player.current_length = prefix_duration
            
            # 重置播放相关状态
            self._play_start_time = time.time()
            self._play_start_pos = 0
            
            # 重置播放完成标记
            self._playback_completed = False
            self._fade_out_started = False
            
            # 更新UI
            songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
            if song_index < len(songs):
                song_path = songs[song_index]
                self.player.current_file = song_path
                self.status_label.config(text=f"播放前缀音: {os.path.basename(song_path)}")
                # 更新高亮到当前歌曲
                self.highlight_playing_song()
                self.update_status_position()
            
            # 启动淡入（使用已有的淡入方法）
            self.player._start_fade_in()

            # ✅ 关键修复：保存歌曲索引到实例变量，避免闭包问题
            self._pending_song_index = song_index
            self._pending_start_pos = start_pos

            # # 计算总延迟时间，只设置前缀音播放完成的定时器（不包含额外延迟）
            # total_delay = int(BGM_TOTAL_DURATION * 1000)
            
            # 设置前缀音完成定时器
            # 使用 lambda 捕获当前的 song_index 和 start_pos，避免变量被修改

            self._prefix_timer_id = self.root.after(
                int(prefix_duration * 1000),
                self._on_prefix_finished
            )
            
            print(f"⏰ 前缀音播放时长: {prefix_duration}s")
            
        except Exception as e:
            print(f"❌ 前缀音播放失败: {e}")
            import traceback
            traceback.print_exc()
            self._is_playing_prefix = False
            self.current_prefix_file = None
            self.play_song_by_index(song_index, start_pos)

    def _on_prefix_finished(self):
        """前缀音播放完成，延迟后播放原曲"""
        # ✅ 从实例变量获取歌曲索引
        song_index = getattr(self, '_pending_song_index', 0)
        start_pos = getattr(self, '_pending_start_pos', None)
                
        print(f"🎵 前缀音播放完成，延迟1秒后播放原曲")
        print(f"   歌曲索引: {song_index}, 起始位置: {start_pos}")

        # 清除前缀音状态
        self._is_playing_prefix = False
        self.current_prefix_file = None
        self._prefix_timer_id = None
        
        # 硬停止前缀音
        self.player._hard_stop()
        
        # 重置播放状态
        self._playback_completed = False
        self._is_transitioning = False
        self._fade_out_started = False
        
        # 延迟1秒后播放原曲
        # 使用 lambda 捕获当前的 song_index 和 start_pos
        self._prefix_to_song_timer = self.root.after(
            1000,
            lambda: self.play_song_by_index(song_index, start_pos)
        )

    def _cancel_prefix_timers(self):
        """取消所有前缀音相关的定时器"""
        for timer_attr in ['_prefix_delay_timer', '_prefix_timer_id', '_prefix_to_song_timer', 
                           '_prefix_fade_out_timer']:
            if hasattr(self, timer_attr):
                try:
                    timer_id = getattr(self, timer_attr)
                    if timer_id:
                        self.root.after_cancel(timer_id)
                        print(f"🔧 取消前缀音定时器: {timer_attr}")
                except Exception as e:
                    print(f"⚠️ 取消定时器 {timer_attr} 失败: {e}")
                finally:
                    setattr(self, timer_attr, None)

        # ✅ 清除前缀音状态
        self._is_playing_prefix = False
        self.current_prefix_file = None

    def load_template_to_editor(self, dance_order, template_name):
        """将模板加载到舞种顺序文本框中"""
        if hasattr(self, 'dance_order_text'):
            self.dance_order_text.delete('1.0', tk.END)
            self.dance_order_text.insert('1.0', '\n'.join(dance_order))
            self.status_label.config(text=f"已加载模板: {template_name}")
        else:
            print("错误: dance_order_text 控件不存在")

    def show_dance_order_generator(self):
        """显示舞种顺序生成器对话框"""
        if not hasattr(self, 'generator'):
            self.generator = DanceOrderPlaylistGenerator(self)
        
        # 创建对话框
        dialog = tk.Toplevel(self.root)
        dialog.title("🎵 舞种顺序歌单生成器")
        dialog.geometry("750x650")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg='#1a1a2e')
        
        # 标题
        tk.Label(dialog, text="🎵 舞种顺序歌单生成器",
                font=('微软雅黑', 16, 'bold'),
                bg='#1a1a2e', fg='#3498db').pack(pady=15)
        
        # ===== 第一部分：舞种顺序输入 =====
        order_frame = tk.LabelFrame(dialog, text="1. 输入舞种顺序", 
                                    bg='#1a1a2e', fg='#ecf0f1',
                                    font=('微软雅黑', 10, 'bold'))
        order_frame.pack(fill=tk.BOTH, expand=False, padx=20, pady=10)
        
        # 文本框
        text_frame = tk.Frame(order_frame, bg='#1a1a2e')
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.dance_order_text = tk.Text(text_frame, font=('微软雅黑', 10),
                                        bg='#2a2a4e', fg='#ecf0f1',
                                        insertbackground='white',
                                        height=8)
        self.dance_order_text.pack(fill=tk.BOTH, expand=True)
        
        # 提示标签
        tk.Label(order_frame, text="💡 支持格式：每行一个舞种 | 带序号如 1,慢三,2,慢四 | 分隔符如 慢三-慢四-探戈",
                bg='#1a1a2e', fg='#7f8c8d', font=('微软雅黑', 8)).pack(anchor='w', padx=10, pady=(0, 5))
        
        # 解析按钮
        btn_row = tk.Frame(order_frame, bg='#1a1a2e')
        btn_row.pack(pady=5)
        
        def on_parse():
            text = self.dance_order_text.get('1.0', tk.END)
            parsed = self.generator.parse_dance_order(text)
            if parsed:
                # 显示解析结果
                self.dance_order_text.delete('1.0', tk.END)
                self.dance_order_text.insert('1.0', '\n'.join(parsed))
                # 统计舞种数和舞曲数
                dance_count = len(set(parsed))
                song_count = len(parsed)
                status_label.config(text=f"✅ 解析成功：检测到 {dance_count} 个舞种，共 {song_count} 首舞曲")
            else:
                messagebox.showwarning("提示", "未能解析出有效的舞种名称")
        
        def on_save_template():
            text = self.dance_order_text.get('1.0', tk.END).strip()
            parsed = self.generator.parse_dance_order(text)
            if not parsed:
                messagebox.showwarning("提示", "舞种顺序为空，无法保存")
                return
            
            name = simpledialog.askstring("保存模板", "请输入模板名称:")
            if name:
                if self.generator.save_template(name, parsed):
                    status_label.config(text=f"✅ 模板已保存: {name}")
                else:
                    messagebox.showerror("错误", "保存模板失败")
        
        def on_load_template():
            self.generator.show_template_manager()
        
        tk.Button(btn_row, text="🔍 解析", command=on_parse,
                bg='#3498db', fg='white', width=10, cursor='hand2').pack(side=tk.LEFT, padx=5)
        tk.Button(btn_row, text="💾 保存模板", command=on_save_template,
                bg='#2ecc71', fg='white', width=10, cursor='hand2').pack(side=tk.LEFT, padx=5)
        tk.Button(btn_row, text="📂 加载模板", command=on_load_template,
                bg='#f39c12', fg='white', width=10, cursor='hand2').pack(side=tk.LEFT, padx=5)
        
        # ===== 第二部分：歌库选择 =====
        library_frame = tk.LabelFrame(dialog, text="2. 选择歌库", 
                                    bg='#1a1a2e', fg='#ecf0f1',
                                    font=('微软雅黑', 10, 'bold'))
        library_frame.pack(fill=tk.X, padx=20, pady=10)
        
        lib_row = tk.Frame(library_frame, bg='#1a1a2e')
        lib_row.pack(pady=10, padx=10)
        
        self.library_paths_var = tk.StringVar(value="")
        lib_entry = tk.Entry(lib_row, textvariable=self.library_paths_var,
                            width=50, bg='#2a2a4e', fg='#ecf0f1',
                            font=('微软雅黑', 9))
        lib_entry.pack(side=tk.LEFT, padx=5)
        
        def on_select_folders():
            folders = filedialog.askdirectory(
                title="选择歌库文件夹（可多选）",
                mustexist=True
            )
            if folders:
                # 如果是单个路径，直接添加
                current = self.library_paths_var.get()
                if current:
                    # 简单处理：如果当前有路径，以分号分隔
                    current_paths = [p.strip() for p in current.split(';') if p.strip()]
                    if folders not in current_paths:
                        current_paths.append(folders)
                    self.library_paths_var.set(';'.join(current_paths))
                else:
                    self.library_paths_var.set(folders)

        def on_scan_library():
            paths_str = self.library_paths_var.get().strip()
            if not paths_str:
                messagebox.showwarning("提示", "请先选择歌库文件夹")
                return
            
            folders = [p.strip() for p in paths_str.split(';') if p.strip()]
            library = self.generator.refresh_library_cache(folders)
            if library:
                status_label.config(text=f"✅ 扫描完成: {len(library)} 种舞种")
                scan_status_label.config(text=f"已加载 {len(library)} 种舞种")

        def on_preview_library():
            """预览歌库舞种"""
            paths_str = self.library_paths_var.get().strip()
            if not paths_str:
                messagebox.showwarning("提示", "请先选择歌库文件夹")
                return
            
            folders = [p.strip() for p in paths_str.split(';') if p.strip()]
            
            def after_preview(modified_map):
                """预览确认后的回调 - 加载歌库并保存修正（不触发前缀音生成）"""
                # 将修正后的映射应用到歌库缓存
                # 重新构建 library_cache
                library = {}
                for file_path, dance in modified_map.items():
                    if dance and dance != "（舞曲）":
                        # 查找对应的显示名称
                        display_name = dance
                        for keyword, display in DANCE_PATTERNS:
                            if dance == keyword:
                                display_name = display
                                break
                            if dance == display:
                                display_name = display
                                break
                        
                        if display_name not in library:
                            library[display_name] = []
                        library[display_name].append(file_path)
                        
                        # ✅ 同步保存到 prefix_manager 的映射（持久化），只保存映射，不触发前缀音生成
                        filename = os.path.basename(file_path)
                        self.prefix_manager.dance_mapping[filename] = display_name

                # ✅ 保存映射文件 - 使用正确的方法名
                self.prefix_manager.save_dance_mapping()

                self.generator.library_cache = library
                self.generator.last_library_paths = folders
                self.generator._save_library_cache()  # ✅ 确保保存到文件
                
                total_files = sum(len(v) for v in library.values())
                scan_status_label.config(text=f"已加载 {len(library)} 个舞种，{total_files} 个文件")
                status_label.config(text=f"✅ 歌库已加载，共 {len(library)} 个舞种")
            
            self.generator.show_library_preview(folders, after_preview)

        def save_dance_mapping(self):
            """保存舞种映射配置"""
            try:
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(self.dance_mapping, f, ensure_ascii=False, indent=2)
                print(f"✅ 已保存 {len(self.dance_mapping)} 条映射到 {self.config_file}")  # 调试
            except Exception as e:
                self.logger.error(f"保存舞种映射失败: {e}")
                print(f"❌ 保存失败: {e}")  # 调试

        def on_clear_paths():
            self.library_paths_var.set("")
            scan_status_label.config(text="未加载歌库")
            status_label.config(text="已清空歌库路径")
        
        tk.Button(lib_row, text="📁 选择文件夹", command=on_select_folders,
                bg='#3498db', fg='white', cursor='hand2').pack(side=tk.LEFT, padx=5)
        tk.Button(lib_row, text="📋 预览", command=on_preview_library,
                bg='#2ecc71', fg='white', cursor='hand2').pack(side=tk.LEFT, padx=5)
        tk.Button(lib_row, text="✕ 清空", command=on_clear_paths,
                bg='#e74c3c', fg='white', cursor='hand2').pack(side=tk.LEFT, padx=5)
        
        scan_status_label = tk.Label(library_frame, text="未加载歌库",
                                    bg='#1a1a2e', fg='#7f8c8d', font=('微软雅黑', 9))
        scan_status_label.pack(anchor='w', padx=10, pady=5)
        
        # ===== 第三部分：状态和操作 =====
        status_label = tk.Label(dialog, text="就绪",
                                bg='#1a1a2e', fg='#ecf0f1', font=('微软雅黑', 10))
        status_label.pack(pady=5)
        
        # ===== 底部按钮 =====
        btn_frame = tk.Frame(dialog, bg='#1a1a2e')
        btn_frame.pack(pady=15)
        
        def on_generate():
            # 获取舞种顺序
            text = self.dance_order_text.get('1.0', tk.END).strip()
            dance_order = self.generator.parse_dance_order(text)
            if not dance_order:
                messagebox.showwarning("提示", "请先输入或解析舞种顺序")
                return
            
            # 获取歌库
            if not self.generator.library_cache:
                messagebox.showwarning("提示", "请先扫描歌库")
                return
            
            # 显示预览
            self.generator.show_preview(dance_order, self.generator.library_cache, 
                                        lambda name, remark: self._confirm_generate(dance_order, name, remark, dialog))
        
        def on_refresh():
            """刷新生成 - 基于当前模板和歌库重新生成"""
            text = self.dance_order_text.get('1.0', tk.END).strip()
            dance_order = self.generator.parse_dance_order(text)
            if not dance_order:
                messagebox.showwarning("提示", "请先输入或解析舞种顺序")
                return
            
            if not self.generator.library_cache:
                messagebox.showwarning("提示", "请先扫描歌库")
                return

            # 检查是否正在播放
            if self.player.is_playing:
                if not messagebox.askyesno("确认刷新", 
                    "当前正在播放歌曲，刷新将移除当前播放列表的所有歌曲并重新生成。\n\n是否继续？"):
                    return
            
            # 显示预览（会使用当前备注）
            self.generator.show_preview(dance_order, self.generator.library_cache,
                                        lambda name, remark: self._confirm_generate(dance_order, name, remark, dialog))
        
        def on_export_m3u():
            if not hasattr(self.generator, 'current_metadata') or not self.generator.current_metadata:
                messagebox.showwarning("提示", "请先生成播放列表")
                return
            playlist = self.playlist_manager.playlists[self.current_playlist]["songs"]
            self.generator.export_playlist(playlist, self.generator.current_metadata, 'm3u')
        
        def on_export_txt():
            if not hasattr(self.generator, 'current_metadata') or not self.generator.current_metadata:
                messagebox.showwarning("提示", "请先生成播放列表")
                return
            playlist = self.playlist_manager.playlists[self.current_playlist]["songs"]
            self.generator.export_playlist(playlist, self.generator.current_metadata, 'txt')
        
        def on_export_excel():
            if not hasattr(self.generator, 'current_metadata') or not self.generator.current_metadata:
                messagebox.showwarning("提示", "请先生成播放列表")
                return
            playlist = self.playlist_manager.playlists[self.current_playlist]["songs"]
            self.generator.export_playlist(playlist, self.generator.current_metadata, 'excel')
        
        def on_show_history():
            self.generator.show_history()
        
        # 主按钮
        main_btn_frame = tk.Frame(btn_frame, bg='#1a1a2e')
        main_btn_frame.pack(pady=5)

        tk.Button(main_btn_frame, text="🎯 生成播放列表", command=on_generate,
                bg='#2ecc71', fg='white', font=('微软雅黑', 11, 'bold'),
                width=15, cursor='hand2').pack(side=tk.LEFT, padx=5)

        tk.Button(main_btn_frame, text="📜 历史", command=on_show_history,
                bg='#e67e22', fg='white', width=8, cursor='hand2').pack(side=tk.LEFT, padx=5)

        # 导出按钮行
        export_frame = tk.Frame(btn_frame, bg='#1a1a2e')
        export_frame.pack(pady=10)
        
        tk.Button(export_frame, text="📤 导出M3U", command=on_export_m3u,
                bg='#9b59b6', fg='white', width=12, cursor='hand2').pack(side=tk.LEFT, padx=5)
        tk.Button(export_frame, text="📤 导出TXT", command=on_export_txt,
                bg='#9b59b6', fg='white', width=12, cursor='hand2').pack(side=tk.LEFT, padx=5)
        tk.Button(export_frame, text="📤 导出Excel", command=on_export_excel,
                bg='#9b59b6', fg='white', width=12, cursor='hand2').pack(side=tk.LEFT, padx=5)
        
        # 自动加载记忆的路径
        if self.generator.last_library_paths:
            self.library_paths_var.set(';'.join(self.generator.last_library_paths))
            # 自动扫描（延迟执行，让界面先显示）
            # dialog.after(500, on_preview_library)


    def _confirm_generate(self, dance_order, playlist_name, remark, dialog):
        """确认生成播放列表"""
        # 检查是否正在播放
        if self.player.is_playing:
            if not messagebox.askyesno("确认生成", 
                "当前正在播放歌曲，生成将新建播放列表并停止播放。\n\n是否继续？"):
                return
        
        # 生成播放列表
        playlist, metadata, warnings = self.generator.generate_playlist(
            dance_order, self.generator.library_cache, remark  # remark 传入生成器
        )
        
        if not playlist:
            messagebox.showwarning("提示", "未能生成任何歌曲\n\n" + '\n'.join(warnings[:5]))
            return
        
        # 新建播放列表
        new_id = self.playlist_manager.create_playlist(playlist_name)
        self.playlist_manager.playlists[new_id]["songs"] = playlist
        # self.playlist_manager.playlists[new_id]["remark"] = remark  # 保存用户备注
        
        # 构建批注信息（历史信息）
        remark_detail = f"生成时间: {metadata.get('generated_time', '')}\n"
        remark_detail += f"舞种数: {metadata.get('dance_count', 0)}\n"
        remark_detail += f"舞曲数: {len(playlist)}\n"
        
        # 舞种顺序压缩成一行
        dance_order_str = "舞种顺序：" + "，".join([f"{i+1}.{dance}" for i, dance in enumerate(dance_order)])
        remark_detail += dance_order_str + "\n"
        
        if remark:
            remark_detail += f"备注: {remark}\n"
        # remark_detail += f"\n舞种顺序:\n"
        # for idx, dance in enumerate(dance_order, 1):
        #     remark_detail += f"  {idx}. {dance}\n"
        
        # 保存批注
        self.playlist_manager.playlists[new_id]["remark"] = remark_detail   # 保存用户备注
        
        self.playlist_manager.save_playlists()
        
        # # 更新播放列表名称（加入元数据）
        # time_str = datetime.datetime.now().strftime("%m%d_%H%M")
        # playlist_name = f"{time_str}_舞曲编排_{len(set(dance_order))}种_{len(playlist)}首"
        # self.playlist_manager.rename_playlist(current_id, playlist_name)
        
        # 更新元数据
        self.generator.current_metadata = metadata
        self.generator.add_history(metadata)
        
        # 刷新显示
        self.update_playlist_buttons()
        self.load_playlist(new_id)
        
        # 显示结果
        msg = f"✅ 已生成 {len(playlist)} 首歌曲\n"
        msg += f"   舞种数: {len(set(dance_order))}\n"
        if warnings:
            msg += f"   ⚠️ 警告: {len(warnings)} 条"
        
        self.status_label.config(text=msg)
        
        # ✅ 生成完成提示框
        success_msg = f"🎉 生成成功！\n\n"
        success_msg += f"列表名称: {playlist_name}\n"
        success_msg += f"歌曲数量: {len(playlist)} 首\n"
        success_msg += f"舞种数量: {len(set(dance_order))} 种\n"
        if remark:
            success_msg += f"备注: {remark}\n"
        if warnings:
            # if messagebox.askyesno("生成完成", 
            #     f"生成完成！共 {len(playlist)} 首歌曲\n\n"
            #     f"有 {len(warnings)} 条警告信息\n"
            #     f"是否查看详情？"):
            #     messagebox.showinfo("警告详情", '\n'.join(warnings))

            success_msg += f"\n⚠️ 警告: {len(warnings)} 条"
        
        messagebox.showinfo("生成完成", success_msg)
        
        # 显示警告详情（如果有）
        if warnings:
            if messagebox.askyesno("查看警告", 
                f"有 {len(warnings)} 条警告信息\n是否查看详情？"):
                messagebox.showinfo("警告详情", '\n'.join(warnings))
        
        # 关闭对话框
        dialog.destroy()

        #     info_display.insert('1.0', info_text if info_text else "（无其他信息）")
        #     info_display.config(state='disabled')
            
        #     # 关闭按钮
        #     tk.Button(remark_window, text="关闭", command=remark_window.destroy,
        #             bg='#95a5a6', fg='white', width=10, cursor='hand2').pack(pady=10)
                
        # # 如果有元数据，更新播放列表描述
        # if metadata:
        #     # 保存元数据到播放列表（用于刷新时使用）
        #     self.playlist_manager.playlists[current_id]["_metadata"] = {
        #         'dance_order': dance_order,
        #         'remark': remark,
        #         'generated_time': metadata.get('generated_time', '')
        #     }
        #     self.playlist_manager.save_playlists()
        
        # 关闭对话框（可选 - 不关闭，让用户可以继续操作）
        # dialog.destroy()


    # ==================== 缓存管理功能 ====================

    def show_cache_manager(self):
        """显示缓存管理器"""
        from prefix_audio import prefix_manager
        
        cache_window = tk.Toplevel(self.root)
        cache_window.title("前缀音缓存管理")
        cache_window.geometry("630x550+400+150")
        cache_window.transient(self.root)
        cache_window.grab_set()
        cache_window.configure(bg='#1a1a2e')
        
        # 获取统计信息
        stats = prefix_manager.get_cache_stats()
        
        # 获取最大缓存限制
        max_cache = getattr(prefix_manager, 'MAX_CACHE_SIZE', 500)
        
        # 标题
        
        tk.Label(cache_window, text="📦 前缀音缓存管理", 
                 font=('微软雅黑', 14, 'bold'),
                 bg='#1a1a2e', fg='#3498db').pack(pady=10)
        
        # 统计信息 - 保存标签引用以便更新
        stats_frame = tk.Frame(cache_window, bg='#1a1a2e')
        stats_frame.pack(fill=tk.X, padx=20, pady=5)
        
        # 显示最大限制
        stats_label = tk.Label(stats_frame, 
            text=f"总缓存数: {stats['total']} / {max_cache}  |  总大小: {stats['total_size_mb']:.2f} MB", 
            bg='#1a1a2e', fg='#ecf0f1', font=('微软雅黑', 10))
        stats_label.pack(side=tk.LEFT)
        
        engine_text = " |  ".join([f"{k}: {v}" for k, v in stats['by_engine'].items()])
        engine_label = tk.Label(stats_frame, text=engine_text, bg='#1a1a2e',
                fg='#7f8c8d', font=('微软雅黑', 9))
        engine_label.pack(side=tk.LEFT, padx=10)
        
        #  状态标签（用于显示操作结果）
        status_label = tk.Label(cache_window, text="就绪", 
                                bg='#1a1a2e', fg='#7f8c8d', 
                                font=('微软雅黑', 9))
        status_label.pack(anchor='w', padx=20, pady=(0, 5))
        
        # 按钮区域
        btn_frame = tk.Frame(cache_window, bg='#1a1a2e')
        btn_frame.pack(fill=tk.X, padx=20, pady=10)
        
        #  刷新函数 - 使用 nonlocal 或直接引用变量
        def refresh_cache_list():
            """刷新缓存列表 - 重新从磁盘加载"""
            try:
                # 重新加载缓存索引
                prefix_manager._load_cache_index()
                
                # 清空树
                for item in tree.get_children():
                    tree.delete(item)


                # ✅ 按创建时间倒序排序
                sorted_items = sorted(
                    prefix_manager.cache_index.items(),
                    key=lambda x: x[1].get('created', ''),
                    reverse=True
                )
                
                for key, info in sorted_items:
                    dance = info.get('dance_name', '未知')
                    config = info.get('config', {})
                    duration = config.get('duration', 8)
                    engine = config.get('engine', '未知')
                    voice = config.get('voice', '默认')
                    created = info.get('created', '未知')
                    
                    tree.insert('', 'end', values=(
                        dance, f"{duration}s", engine, voice, created[:16]
                    ), tags=(key,))
                
                # 更新统计
                stats = prefix_manager.get_cache_stats()
                max_cache = getattr(prefix_manager, 'MAX_CACHE_SIZE', 500)
                # ✅ 更新时显示最大限制
                stats_label.config(text=f"总缓存数: {stats['total']} / {max_cache}  |  总大小: {stats['total_size_mb']:.2f} MB")
                
                engine_text = " |  ".join([f"{k}: {v}" for k, v in stats['by_engine'].items()])
                engine_label.config(text=engine_text)
                
                status_label.config(text=f" 已刷新，当前 {stats['total']} 个缓存", fg='#2ecc71')
                
            except Exception as e:
                status_label.config(text=f"❌ 刷新失败: {e}", fg='#e74c3c')
                print(f"刷新缓存失败: {e}")
        
        def clear_all_cache():
            if messagebox.askyesno("确认清空", "确定要清空所有前缀音缓存吗？"):
                try:
                    if prefix_manager.clear_all_cache():
                        refresh_cache_list()
                        status_label.config(text="✅ 已清空所有缓存", fg='#2ecc71')
                        messagebox.showinfo("完成", "缓存已清空")
                except Exception as e:
                    status_label.config(text=f"❌ 清空失败: {e}", fg='#e74c3c')
        
        def clean_old_cache():
            if messagebox.askyesno("确认清理", "确定要清理过期缓存吗？"):
                try:
                    cleaned = prefix_manager.clean_cache()
                    refresh_cache_list()
                    status_label.config(text=f" 已清理 {cleaned} 个过期缓存", fg='#2ecc71')
                    messagebox.showinfo("完成", f"已清理 {cleaned} 个过期缓存")
                except Exception as e:
                    status_label.config(text=f"❌ 清理失败: {e}", fg='#e74c3c')
        
        tk.Button(btn_frame, text="🔄 刷新", command=refresh_cache_list,
                  bg='#3498db', fg='white', cursor='hand2', width=25).pack(side=tk.LEFT, padx=5)
        
        tk.Button(btn_frame, text="🧹 清理过期", command=clean_old_cache,
                  bg='#f39c12', fg='white', cursor='hand2', width=25).pack(side=tk.LEFT, padx=5)
        
        tk.Button(btn_frame, text="🗑️ 全部清空", command=clear_all_cache,
                  bg='#e74c3c', fg='white', cursor='hand2', width=25).pack(side=tk.LEFT, padx=5)
        
        # 状态标签
        status_label = tk.Label(cache_window, text="就绪", 
                                bg='#1a1a2e', fg='#7f8c8d', 
                                font=('微软雅黑', 9))
        status_label.pack(anchor='w', padx=20, pady=(0, 5))
        
        # 缓存列表
        tree_frame = tk.Frame(cache_window, bg='#1a1a2e')
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)
        
        columns = ('舞种', '时长', '引擎', '音色', '创建时间')
        tree = ttk.Treeview(tree_frame, columns=columns, show='headings', height=15)
        
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=50, anchor='center')
        
        tree.column('舞种', width=80)
        tree.column('音色', width=180)
        tree.column('创建时间', width=150)
        
        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 右键菜单
        def show_cache_context_menu(event):
            item = tree.identify_row(event.y)
            if not item:
                return
            tree.selection_set(item)
            
            menu = tk.Menu(cache_window, tearoff=0)
            menu.add_command(label="查看详情", command=lambda: show_cache_detail(item))
            menu.add_command(label="删除此缓存", command=lambda: delete_selected_cache())
            menu.post(event.x_root, event.y_root)
        
        tree.bind('<Button-3>', show_cache_context_menu)
        
        def delete_selected_cache():
            selection = tree.selection()
            if not selection:
                return
            
            if messagebox.askyesno("确认删除", "确定要删除选中的缓存吗？"):
                try:
                    deleted_count = 0
                    for item in selection:
                        tags = tree.item(item, 'tags')
                        if tags:
                            key = tags[0]
                            if key in prefix_manager.cache_index:
                                file_path = prefix_manager.cache_index[key].get('file')
                                if file_path and os.path.exists(file_path):
                                    try:
                                        os.remove(file_path)
                                    except:
                                        pass
                                del prefix_manager.cache_index[key]
                                deleted_count += 1
                    if deleted_count > 0:
                        prefix_manager._save_cache_index()
                        refresh_cache_list()
                        status_label.config(text=f" 已删除 {deleted_count} 个缓存", fg='#2ecc71')
                except Exception as e:
                    status_label.config(text=f"❌ 删除失败: {e}", fg='#e74c3c')
        
        def show_cache_detail(item):
            """显示缓存详情"""
            tags = tree.item(item, 'tags')
            if not tags:
                return
            key = tags[0]
            info = prefix_manager.cache_index.get(key, {})
            
            detail = f"缓存键: {key}\n"
            detail += f"舞种: {info.get('dance_name', '未知')}\n"
            detail += f"文件: {info.get('file', '未知')}\n"
            detail += f"创建时间: {info.get('created', '未知')}\n"
            config = info.get('config', {})
            detail += f"\n配置信息:\n"
            detail += f"  音量: {config.get('volume', 0.2)}\n"
            detail += f"  时长: {config.get('duration', 8)}s\n"
            detail += f"  文本: {config.get('speech_text', '下面请欣赏')}\n"
            detail += f"  位置: {config.get('position', 'middle')}\n"
            detail += f"  引擎: {config.get('engine', 'edge')}\n"
            detail += f"  音色: {config.get('voice', '默认')}\n"
            
            messagebox.showinfo("缓存详情", detail)
        
        #  首次加载数据
        refresh_cache_list()

    # ==================== 设置功能 ====================
    
    def show_settings(self):
        """显示设置窗口"""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("设置")
        settings_window.geometry("300x550")
        settings_window.transient(self.root)
        settings_window.grab_set()
        
        tk.Label(settings_window, text="默认歌曲设置:", font=('微软雅黑', 12, 'bold')).pack(pady=10)
        
        fields = [
            ("默认起始时间(秒):", 'start_time'),
            ("默认播放时长(秒, 0=完整):", 'play_duration'),
            ("默认停顿时长(秒):", 'pause_duration'),
            ("默认音量(0-100):", 'volume'),
            ("默认速度(50-150):", 'speed'),
            ("默认音调(-12到12):", 'pitch'),
            ("默认滑入参数(秒):", 'fade_in_duration'),
            ("默认滑出参数(秒):", 'fade_out_duration'),
        ]
        
        vars_dict = {}
        for label_text, key in fields:
            tk.Label(settings_window, text=label_text).pack()
            var = tk.StringVar(value=str(self.default_settings[key]))
            tk.Entry(settings_window, textvariable=var, width=12).pack(pady=5)
            vars_dict[key] = var

        def save_settings():
            try:
                for key in vars_dict:
                    if key in ['volume', 'speed', 'pitch']:
                        self.default_settings[key] = int(vars_dict[key].get())
                    else:
                        self.default_settings[key] = float(vars_dict[key].get())
                
                self.player.fade_in_duration = self.default_settings['fade_in_duration']
                self.player.fade_out_duration = self.default_settings['fade_out_duration']
                
                self.load_playlist(self.current_playlist)
                settings_window.destroy()
                self.status_label.config(text="设置已保存")
            except ValueError:
                messagebox.showerror("错误", "请输入有效的数字")
        
        tk.Button(settings_window, text="保存", command=save_settings,
                 bg='#2ecc71', fg='white', width=15).pack(pady=20)
    
    def set_library_dir(self):
        """设置歌库目录"""
        folder = filedialog.askdirectory(title="选择歌库目录")
        if folder:
            self.song_library_dir = folder
            self.load_folder_tree(folder)
            self.status_label.config(text=f"歌库目录已设置为: {folder}")
    
    # ==================== 其他功能 ====================
    
    def clean_temp_files(self):
        self.player.clean_temp_files()
        self.status_label.config(text="临时文件已清理")
    
    def show_shortcut_settings(self):
        """显示快捷键设置"""
        messagebox.showinfo("快捷键设置", "快捷键列表:\n\n"
                          "Ctrl+O: 打开文件\n"
                          "Ctrl+Shift+O: 打开文件夹\n"
                          "Ctrl+F: 搜索\n\n"
                          "Space: 播放/暂停\n"
                          "Left: 上一首\n"
                          "Right: 下一首\n"
                          "F2: 减少音量\n"
                          "F3: 增加音量\n\n"
                          "F4: 返回播放列表\n"
                          "Delete: 删除选中项\n")
    
    def set_play_mode(self, mode):
        """设置播放模式"""
        self.player.play_mode = mode
        mode_names = {"sequential": "顺序播放", "single_loop": "单曲循环", "random": "随机播放"}
        self.status_play_mode_label.config(text=f"播放模式: {mode_names[mode]}")
        self.status_label.config(text=f"播放模式: {mode_names[mode]}")
        
        modes = ['sequential', 'single_loop', 'random']
        for i, m in enumerate(modes):
            if m == mode:
                self.play_mode_submenu.entryconfig(i, label=f"▶ {mode_names[m]}")
            else:
                self.play_mode_submenu.entryconfig(i, label=f"  {mode_names[m]}")
    
    def send_to_temp_and_play(self):
        """发送到临时列表并播放"""
        selection = self.song_table.selection()
        if selection:
            item = selection[0]
            values = self.song_table.item(item, 'values')
            song_index = int(values[0]) - 1
            songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
            if song_index < len(songs):
                song = songs[song_index]
                self.playlist_manager.add_song(1, song)
                self.load_playlist(1)
                new_songs = self.playlist_manager.playlists[1]["songs"]
                new_index = len(new_songs) - 1
                self.player.playlist = new_songs
                self.player.current_index = new_index
                self.play_song_by_index(new_index)
    
    def delete_selected(self):
        """删除选中项"""
        selection = self.song_table.selection()
        if selection:
            item = selection[0]
            values = self.song_table.item(item, 'values')
            song_index = int(values[0]) - 1
            self.playlist_manager.remove_song(self.current_playlist, song_index)
            self.load_playlist(self.current_playlist)
            self.status_label.config(text="已删除选中项")
    
    def show_table_context_menu(self, event):
        """显示表格右键菜单"""
        item = self.song_table.identify_row(event.y)
        if item:
            self.song_table.selection_set(item)
            context_menu = tk.Menu(self.root, tearoff=0)
            context_menu.add_command(label="播放", command=self.play_music)
            context_menu.add_command(label="删除", command=self.delete_selected)
            context_menu.add_command(label="重命名", command=self.rename_file)
            context_menu.add_separator()
            context_menu.add_command(label="编辑舞种", command=self.show_dance_name_editor)
            context_menu.add_command(label="编辑歌曲信息", command=self.show_song_edit_dialog)
            context_menu.add_command(label="重置该歌曲配置", command=self.reset_song_config)
            context_menu.add_separator()
            context_menu.add_command(label="打开文件所在目录", command=self.open_file_location)
            context_menu.add_command(label="发送到临时列表并播放", command=self.send_to_temp_and_play)
            context_menu.add_command(label="删除文件", command=self.delete_file)
            context_menu.post(event.x_root, event.y_root)
    
    def reset_song_config(self):
        """重置选中歌曲的配置"""
        selection = self.song_table.selection()
        if selection:
            item = selection[0]
            values = self.song_table.item(item, 'values')
            song_index = int(values[0]) - 1
            songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
            if song_index < len(songs):
                song_path = songs[song_index]
                if song_path in self.song_configs:
                    del self.song_configs[song_path]
                    self.save_song_configs()
                    self.load_playlist(self.current_playlist)
                    self.status_label.config(text="歌曲配置已重置")
    
    def show_song_edit_dialog(self):
        """显示单曲播放状态编辑对话框"""
        selection = self.song_table.selection()
        if not selection:
            return
        
        item = selection[0]
        values = self.song_table.item(item, 'values')
        song_index = int(values[0]) - 1
        songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
        
        if song_index >= len(songs):
            return
        
        song_path = songs[song_index]
        config = self.song_configs.get(song_path, {})
        song_duration = self.get_audio_duration_seconds_cached(song_path)
        
        dialog = tk.Toplevel(self.root)
        dialog.title(f"编辑歌曲: {os.path.basename(song_path)}")
        dialog.geometry("250x250+635+365")
        dialog.transient(self.root)
        dialog.grab_set()

        main_frame = tk.Frame(dialog)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        edit_frame = tk.Frame(main_frame)
        edit_frame.grid(row=0, column=0, sticky='nsew')

        button_frame = tk.Frame(main_frame)
        button_frame.grid(row=0, column=1, sticky='ns', padx=(15, 0))

        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_columnconfigure(1, weight=0)

        labels = [
            ("起始时间(秒):", 'start_time', self.default_settings['start_time']),
            ("播放时长(秒):", 'play_duration', 0),
            ("停顿时长(秒):", 'pause_duration', self.default_settings['pause_duration']),
            ("音量(0-100):", 'volume', self.default_settings['volume']),
            ("速度(50-150):", 'speed', self.default_settings['speed']),
            ("音调(-12到12):", 'pitch', self.default_settings['pitch']),
            ("灯光(用脚本):", 'light', ''),
        ]
        
        vars_dict = {}
        for i, (label_text, key, default_val) in enumerate(labels):
            tk.Label(edit_frame, text=label_text, anchor='e', width=12).grid(row=i, column=0, sticky='e', pady=4)
            var = tk.StringVar(value=str(config.get(key, default_val)))
            tk.Entry(edit_frame, textvariable=var, width=8).grid(row=i, column=1, pady=4, padx=(5, 0))
            vars_dict[key] = var

        def save_current_config():
            try:
                new_config = {
                    'start_time': float(vars_dict['start_time'].get()),
                    'play_duration': int(float(vars_dict['play_duration'].get())),
                    'pause_duration': float(vars_dict['pause_duration'].get()),
                    'volume': int(vars_dict['volume'].get()),
                    'speed': int(vars_dict['speed'].get()),
                    'pitch': int(vars_dict['pitch'].get()),
                    'light': vars_dict['light'].get()
                }
                self.song_configs[song_path] = new_config
                self.save_song_configs()
                self.load_playlist(self.current_playlist)
                self.status_label.config(text="歌曲配置已保存")
                return True
            except ValueError:
                messagebox.showerror("错误", "请输入有效的数字")
                return False

        def switch_song(direction):
            if not save_current_config():
                return
            
            new_index = song_index + direction
            
            if 0 <= new_index < len(songs):
                self.song_table.selection_set(self.song_table.get_children()[new_index])
                dialog.destroy()
                self.show_song_edit_dialog()
            else:
                if direction > 0:
                    self.status_label.config(text="已经是最后一首歌曲")
                    messagebox.showinfo("提示", "已经是最后一首歌曲")
                else:
                    self.status_label.config(text="已经是第一首歌曲")
                    messagebox.showinfo("提示", "已经是第一首歌曲")

        def prev_song():
            switch_song(-1)

        def next_song():
            switch_song(1)        

        tk.Button(button_frame, text="上一曲", command=prev_song, 
                bg='#3498db', fg='white', width=8).pack(pady=15)
        tk.Button(button_frame, text="重置", command=self.reset_song_config,
                bg="#d03434", fg='white', width=8).pack(pady=15)
        tk.Button(button_frame, text="下一曲", command=next_song,
                bg='#3498db', fg='white', width=8).pack(pady=15)
    
    # def on_table_double_click(self, event):
    #     """表格双击事件 - 双击任意位置从头播放"""
    #     item = self.song_table.identify_row(event.y)
    #     if item:
    #         self.song_table.selection_set(item)
    #         values = self.song_table.item(item, 'values')
    #         song_index = int(values[0]) - 1
    #         # 使用新的播放方法（支持前缀音）
    #         self.play_with_prefix(song_index)
    #         # self.play_song_by_index(song_index)

    def on_table_double_click(self, event):
        """表格双击事件 - 双击任意位置从头播放"""
        item = self.song_table.identify_row(event.y)
        if item:
            self.song_table.selection_set(item)
            values = self.song_table.item(item, 'values')
            song_index = int(values[0]) - 1

            # ✅ 修复：先将当前列表设置为播放列表，确保播放正确的歌曲
            # 但更好的做法是修改 play_with_prefix 使用正确的列表
            
            # 方案：在双击时，如果当前查看的列表不是播放列表，
            # 但我们需要播放当前查看的列表中的歌曲
            # 所以应该用 self.current_playlist 来获取歌曲
            
            # 获取歌曲路径
            songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
            if song_index < len(songs):
                song_path = songs[song_index]
                # 查找这首歌在哪个播放列表中
                for pid, pdata in self.playlist_manager.playlists.items():
                    if song_path in pdata["songs"]:
                        # 如果找到，使用该列表播放
                        self.playing_playlist_id = pid
                        break
                else:
                    # 如果没找到，使用当前列表
                    self.playing_playlist_id = self.current_playlist

            self.play_with_prefix(song_index)

    def on_table_drag_start(self, event):
        """表格拖动开始"""
        item = self.song_table.identify_row(event.y)
        if item:
            self._drag_start_index = self.song_table.index(item)
            self._drag_target_index = self._drag_start_index
            self._dragged_item = item

    def on_table_drag_motion(self, event):
        """表格拖动过程中"""
        if self._drag_start_index is None:
            return
        
        target_item = self.song_table.identify_row(event.y)
        if target_item:
            target_index = self.song_table.index(target_item)
            
            if target_index != self._drag_target_index:
                self._drag_target_index = target_index
                self.show_drag_indicator(target_index, event.y)

    def on_table_drag_end(self, event):
        """表格拖动结束"""
        if self._drag_start_index is None:
            return
        
        target_item = self.song_table.identify_row(event.y)
        if target_item:
            target_index = self.song_table.index(target_item)
            
            if target_index != self._drag_start_index:
                self.move_song_in_playlist(self._drag_start_index, target_index)
        
        self.clear_drag_indicator()
        
        self._drag_start_index = None
        self._drag_target_index = None
        self._dragged_item = None

    def show_drag_indicator(self, target_index, y_pos):
        """显示拖动指示（使用行高亮）"""
        self.clear_drag_indicator()
        
        items = self.song_table.get_children()
        if target_index < len(items):
            target_item = items[target_index]
            bbox = self.song_table.bbox(target_item)
            if bbox:
                x, y, width, height = bbox
                
                if y_pos < y + height / 2:
                    self.song_table.item(target_item, tags=('drag_target',))
                    if target_index > 0:
                        prev_item = items[target_index - 1]
                        self.song_table.item(prev_item, tags=())
                else:
                    self.song_table.item(target_item, tags=('drag_target',))
                    if target_index < len(items) - 1:
                        next_item = items[target_index + 1]
                        self.song_table.item(next_item, tags=())
                
                self.song_table.tag_configure('drag_target', background='#ffcccc')

    def clear_drag_indicator(self):
        """清除拖动指示"""
        items = self.song_table.get_children()
        for item in items:
            self.song_table.item(item, tags=())
        self._drag_indicator = None

    def move_song_in_playlist(self, from_index, to_index):
        """在播放列表中移动歌曲"""
        songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
        
        if 0 <= from_index < len(songs) and 0 <= to_index < len(songs):
            if self.playlist_manager.move_song(self.current_playlist, from_index, to_index):
                self.load_playlist(self.current_playlist)
                self.status_label.config(text="歌曲顺序已调整")
                
                if self.player.current_index == from_index:
                    self.player.current_index = to_index
                elif from_index < self.player.current_index <= to_index:
                    self.player.current_index -= 1
                elif to_index <= self.player.current_index < from_index:
                    self.player.current_index += 1

    def update_status_position(self):
        """更新当前播放位置信息"""
        if self.player.current_index >= 0:
            # ✅ 使用正在播放的列表ID，而不是当前查看的列表
            playlist_id = self.playing_playlist_id
            if playlist_id is None:
                playlist_id = self.current_playlist
            
            # 检查播放列表是否存在
            if playlist_id in self.playlist_manager.playlists:
                total = len(self.playlist_manager.playlists[playlist_id]["songs"])
                self.status_position_label.config(text=f"{self.player.current_index + 1}/{total}")
            else:
                self.status_position_label.config(text="0/0")
        else:
            self.status_position_label.config(text="0/0")

    def get_bpm(self, file_path):
        """使用多种方法检测 BPM，取平均值"""
        try:
            y, sr = librosa.load(file_path, sr=22050)
            
            bpm_values = []
            
            try:
                tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
                if isinstance(tempo, np.ndarray):
                    tempo = tempo[0]
                bpm_values.append(float(tempo))
            except:
                pass
            
            try:
                onset_env = librosa.onset.onset_strength(y=y, sr=sr)
                tempo = librosa.feature.rhythm.tempo(onset_envelope=onset_env, sr=sr)
                if isinstance(tempo, np.ndarray):
                    tempo = tempo[0]
                bpm_values.append(float(tempo))
            except:
                pass
            
            try:
                tempo, _ = librosa.beat.beat_track(y=y, sr=sr, hop_length=256)
                if isinstance(tempo, np.ndarray):
                    tempo = tempo[0]
                bpm_values.append(float(tempo))
            except:
                pass
            
            if bpm_values:
                avg_bpm = np.mean(bpm_values)
                return f"{avg_bpm:.0f} BPM"
            else:
                return "N/A"
                
        except Exception as e:
            print(f"BPM 检测失败: {e}")
            return "N/A"
        
    def detect_bpm_async(self, file_path):
        """在后台线程中检测 BPM"""
        def detect_and_update():
            try:
                bpm = self.get_bpm(file_path)
                self.bpm_cache[file_path] = bpm
                
                if hasattr(self, 'metadata_text') and self.metadata_text.winfo_exists():
                    self.metadata_text.after(0, self.update_bpm_display, bpm)
            except Exception as e:
                print(f"BPM 检测出错: {e}")
        
        thread = threading.Thread(target=detect_and_update, daemon=True)
        self.bpm_threads[file_path] = thread
        thread.start()
    
    def update_bpm_display(self, bpm):
        """更新 BPM 显示"""
        try:
            current_text = self.metadata_text.get('1.0', tk.END)
            
            lines = current_text.split('\n')
            updated_lines = []
            for line in lines:
                if line.startswith("BPM:"):
                    updated_lines.append(f"BPM: {bpm}")
                else:
                    updated_lines.append(line)
            
            self.metadata_text.delete('1.0', tk.END)
            self.metadata_text.insert('1.0', '\n'.join(updated_lines))
        except Exception as e:
            print(f"更新 BPM 显示出错: {e}")

    def show_metadata(self, file_path):
        """显示歌曲元数据信息"""
        try:
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            duration = self.get_audio_duration_seconds_cached(file_path)
            
            if file_size < 1024:
                size_str = f"{file_size} B"
            elif file_size < 1024 * 1024:
                size_str = f"{file_size / 1024:.1f} KB"
            else:
                size_str = f"{file_size / (1024 * 1024):.1f} MB"

            file_ext = os.path.splitext(file_path)[1].lower()
            
            bitrate = "N/A"
            sample_rate = "N/A"
            channels = "N/A"
            bit_depth = "N/A"
            bpm = "N/A"
            
            try:
                if file_ext == '.mp3':
                    audio = MP3(file_path)
                    if hasattr(audio.info, 'bitrate'):
                        bitrate = f"{audio.info.bitrate / 1000:.0f} kbps"
                    if hasattr(audio.info, 'sample_rate'):
                        sample_rate = f"{audio.info.sample_rate} Hz"
                    if hasattr(audio.info, 'channels'):
                        channels = audio.info.channels
                    bit_depth = "N/A"
                    
                    if 'TBPM' in audio:
                        bpm = str(audio['TBPM'])
                    
                elif file_ext == '.flac':
                    audio = FLAC(file_path)
                    if hasattr(audio.info, 'bitrate'):
                        bitrate = f"{audio.info.bitrate / 1000:.0f} kbps"
                    if hasattr(audio.info, 'sample_rate'):
                        sample_rate = f"{audio.info.sample_rate} Hz"
                    if hasattr(audio.info, 'channels'):
                        channels = audio.info.channels
                    if hasattr(audio.info, 'bits_per_sample'):
                        bit_depth = f"{audio.info.bits_per_sample} bit"
                    
                    if 'bpm' in audio:
                        bpm = str(audio['bpm'][0])
                        
                elif file_ext == '.wav':
                    audio = WAVE(file_path)
                    if hasattr(audio.info, 'bitrate'):
                        bitrate = f"{audio.info.bitrate / 1000:.0f} kbps"
                    if hasattr(audio.info, 'sample_rate'):
                        sample_rate = f"{audio.info.sample_rate} Hz"
                    if hasattr(audio.info, 'channels'):
                        channels = audio.info.channels
                    if hasattr(audio.info, 'bits_per_sample'):
                        bit_depth = f"{audio.info.bits_per_sample} bit"
                    
                elif file_ext == '.ogg':
                    audio = OggVorbis(file_path)
                    if hasattr(audio.info, 'bitrate'):
                        bitrate = f"{audio.info.bitrate / 1000:.0f} kbps"
                    if hasattr(audio.info, 'sample_rate'):
                        sample_rate = f"{audio.info.sample_rate} Hz"
                    if hasattr(audio.info, 'channels'):
                        channels = audio.info.channels
                    bit_depth = "N/A"
                    
                    if 'bpm' in audio:
                        bpm = str(audio['bpm'][0])
                        
                elif file_ext in ['.m4a', '.mp4', '.aac']:
                    audio = MP4(file_path)
                    if hasattr(audio.info, 'bitrate'):
                        bitrate = f"{audio.info.bitrate / 1000:.0f} kbps"
                    if hasattr(audio.info, 'sample_rate'):
                        sample_rate = f"{audio.info.sample_rate} Hz"
                    if hasattr(audio.info, 'channels'):
                        channels = audio.info.channels
                    bit_depth = "N/A"
                    
            except Exception as e:
                print(f"读取音频元数据时出错: {e}")

            bpm = self.get_bpm(file_path)
            
            metadata = f"文件名: {file_name}\n"
            metadata += f"文件大小: {size_str}\n"
            metadata += f"节拍速度: {bpm}\n"
            metadata += f"比特率: {bitrate}\n"
            metadata += f"采样率: {sample_rate}\n"
            metadata += f"声道数: {channels}\n"
            metadata += f"位深度: {bit_depth}\n"

            self.metadata_text.delete('1.0', tk.END)
            self.metadata_text.insert('1.0', metadata)
            
        except Exception as e:
            self.metadata_text.delete('1.0', tk.END)
            self.metadata_text.insert('1.0', f"无法获取歌曲信息: {e}")
    
    def update_time(self):
        """更新日期时间显示"""
        now = datetime.datetime.now()
        time_str = now.strftime("%m月%d日 %H:%M")
        self.status_time_label.config(text=time_str)
        self.root.after(5000, self.update_time)
    
    def show_about(self):
        """显示软件信息"""
        messagebox.showinfo("关于", "舞厅舞曲播放编排系统\n\n"
                          "版本: 1.2.0\n"
                          "作者: 魅影制作\n"
                          "版权: © 2026")
    
    def show_help(self):
        """显示帮助"""
        messagebox.showinfo("帮助", "使用说明:\n\n"
                          "1. 单曲重置配置：右键点击表格里歌曲仅针对单曲编辑和重置\n"
                          "2. 列表重置配置：右键播放列表可重置该列表所有歌曲配置\n"
                          "3. 鼠标悬停会有详细的提示帮助")
    
    def check_updates(self):
        """检查更新"""
        messagebox.showinfo("检查更新", "当前已是最新版本")


if __name__ == "__main__":
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except:
        root = tk.Tk()
    
    app = DanceMusicPlayer(root)

    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
    if os.path.exists(icon_path):
        root.iconbitmap(icon_path)
        root.update_idletasks()

    root.mainloop()