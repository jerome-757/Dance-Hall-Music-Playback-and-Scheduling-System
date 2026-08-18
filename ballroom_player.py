import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import os
import datetime
import json
import threading
import time
import random
from pathlib import Path
import pygame
import shutil
from PIL import Image, ImageTk, ImageDraw
import mutagen
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.wave import WAVE
from mutagen.oggvorbis import OggVorbis
from mutagen.mp4 import MP4
import librosa
import numpy as np


class MusicPlayerCore:
    """音乐播放核心类"""
    def __init__(self):
        super().__init__()
        # 优化音频初始化
        pygame.mixer.pre_init(44100, -16, 2, 4096)
        pygame.mixer.init()
        pygame.mixer.music.set_volume(0.8)
        self.current_file = None
        self.is_playing = False
        self.is_paused = False
        self.volume = 80
        self.play_mode = "sequential"  # sequential, random, single_loop
        self.current_position = 0
        self.playlist = []
        self.current_index = -1
        self.fade_out_duration = 3  # 滑音参数（秒）
        self._fade_thread = None
        self._stop_fade = False
        self.current_length = 0  # 缓存当前歌曲时长
        self._length_cache = {}  # 所有歌曲时长缓存

    def load(self, file_path):
        """加载音乐文件"""
        try:
            self.stop()
            time.sleep(0.1)
            pygame.mixer.music.load(file_path)
            self.current_file = file_path
            self.current_position = 0
            return True
        except Exception as e:
            print(f"加载失败: {e}")
            return False
    
    def play(self, file_path=None, start_pos=0):
        """播放音乐"""
        try:
            if file_path:
                if not self.load(file_path):
                    return False
            
            if self.current_file:
                # 从缓存获取时长
                if self.current_file in self._length_cache:
                    self.current_length = self._length_cache[self.current_file]
                else:
                    self.current_length = self.get_length()
                    self._length_cache[self.current_file] = self.current_length
                pygame.mixer.music.stop()
                time.sleep(0.05)
                pygame.mixer.music.load(self.current_file)
                pygame.mixer.music.set_volume(self.volume / 100)
                
                if start_pos > 0:
                    pygame.mixer.music.play(start=start_pos)
                else:
                    pygame.mixer.music.play()
                
                self.is_playing = True
                self.is_paused = False
                return True
            return False
        except Exception as e:
            print(f"播放失败: {e}")
            return False
    
    def pause(self):
        """暂停播放（带滑音效果）"""
        if self.is_playing and not self.is_paused:
            self._fade_out_and_pause()
    
    def _fade_out_and_pause(self):
        """滑音后暂停"""
        self._stop_fade = False
        def fade_out():
            try:
                current_vol = self.volume
                steps = int(self.fade_out_duration * 10)
                if steps <= 0:
                    steps = 1
                vol_step = current_vol / steps
                
                for i in range(steps):
                    if self._stop_fade:
                        break
                    new_vol = current_vol - (vol_step * (i + 1))
                    pygame.mixer.music.set_volume(max(0, new_vol) / 100)
                    time.sleep(0.1)
                
                if not self._stop_fade:
                    pygame.mixer.music.pause()
                    self.is_paused = True
                    self.is_playing = False
                    pygame.mixer.music.set_volume(self.volume / 100)
            except Exception as e:
                print(f"滑音暂停失败: {e}")
                pygame.mixer.music.pause()
                self.is_paused = True
                self.is_playing = False
        
        self._fade_thread = threading.Thread(target=fade_out, daemon=True)
        self._fade_thread.start()
    
    def resume(self):
        """恢复播放"""
        self._stop_fade = True
        if self.is_paused:
            try:
                pygame.mixer.music.set_volume(self.volume / 100)
                pygame.mixer.music.unpause()
                self.is_paused = False
                self.is_playing = True
            except:
                pass
    
    def stop(self):
        """停止播放"""
        self._stop_fade = True
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        except:
            pass
        self.is_playing = False
        self.is_paused = False
        self.current_position = 0
    
    def set_volume(self, volume):
        """设置音量"""
        self.volume = max(0, min(100, volume))
        try:
            pygame.mixer.music.set_volume(self.volume / 100)
        except:
            pass
    
    def get_position(self):
        """获取当前播放位置（秒）"""
        if self.is_playing or self.is_paused:
            try:
                pos = pygame.mixer.music.get_pos()
                if pos >= 0:
                    return pos / 1000.0
            except:
                pass
        return 0
    
    def get_length(self):
        """获取音乐长度（秒）- 使用缓存"""
        if self.current_file in self._length_cache:
            return self._length_cache[self.current_file]
        
        if self.current_file:
            try:
                sound = pygame.mixer.Sound(self.current_file)
                length = sound.get_length()
                self._length_cache[self.current_file] = length
                return length
            except:
                try:
                    import mutagen
                    audio = mutagen.File(self.current_file)
                    if audio and hasattr(audio, 'info'):
                        length = audio.info.length
                        self._length_cache[self.current_file] = length
                        return length
                except:
                    pass
        return 0
        
    def set_position(self, position):
        """设置播放位置"""
        if self.current_file and position >= 0:
            try:
                was_playing = self.is_playing or self.is_paused
                pygame.mixer.music.stop()
                time.sleep(0.05)
                pygame.mixer.music.play(start=position)
                pygame.mixer.music.set_volume(self.volume / 100)
                if was_playing:
                    self.is_playing = True
                    self.is_paused = False
                return True
            except Exception as e:
                print(f"设置位置失败: {e}")
        return False
    
    def next(self):
        """下一首"""
        if not self.playlist:
            return None
        
        if self.play_mode == "random":
            self.current_index = random.randint(0, len(self.playlist) - 1)
        elif self.play_mode == "single_loop":
            pass
        else:  # sequential
            self.current_index = (self.current_index + 1) % len(self.playlist)
        
        if self.current_index < len(self.playlist):
            return self.playlist[self.current_index]
        return None
    
    def previous(self):
        """上一首"""
        if not self.playlist:
            return None
        
        if self.play_mode == "random":
            self.current_index = random.randint(0, len(self.playlist) - 1)
        else:
            self.current_index = (self.current_index - 1) % len(self.playlist)
        
        if self.current_index < len(self.playlist):
            return self.playlist[self.current_index]
        return None


class PlaylistManager:
    """播放列表管理类"""
    def __init__(self, parent):
        self.parent = parent
        self.playlists = {
            1: {"name": "临时列表", "songs": [], "file": None},
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
                    "file": value["file"]
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
        """创建新播放列表"""
        new_id = max(self.playlists.keys()) + 1
        self.playlists[new_id] = {"name": name, "songs": [], "file": None}
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
        
        # 默认设置
        self.default_settings = {
            'start_time': 0,
            'play_duration': 0,  # 0表示完整播放
            'pause_duration': 0,
            'volume': 80,
            'fade_out_duration': 3
        }
        
        # 设置样式
        self.setup_styles()
        
        # 创建界面
        self.create_menu_bar()
        self.create_control_bar()
        self.create_main_content()
        
        # 初始化变量
        self.current_playlist = 1
        self.song_library_dir = None
        self.is_dragging = False
        self.drag_item = None
        self.progress_dragging = False
        self._update_progress_flag = False  # 进度条更新标志
        
        self.setup_shortcuts()
        self.setup_drag_drop()
        
        # 启动进度更新线程
        self.update_progress_thread()
        
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
        file_menu.add_separator()
        file_menu.add_command(label="快捷键设置", command=self.show_shortcut_settings)
        file_menu.add_command(label="灯光控制", command=self.show_light_control)
        file_menu.add_command(label="设置", command=self.show_settings)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.root.quit)
        
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
        
        # 播放模式子菜单
        self.play_mode_submenu = tk.Menu(play_menu, tearoff=0)
        self.play_mode_submenu.add_command(label="▶ 顺序播放", command=lambda: self.set_play_mode("sequential"))
        self.play_mode_submenu.add_command(label="  单曲循环", command=lambda: self.set_play_mode("single_loop"))
        self.play_mode_submenu.add_command(label="  随机播放", command=lambda: self.set_play_mode("random"))
        play_menu.add_cascade(label="播放模式 ▸", menu=self.play_mode_submenu)
        
        # 曲目列表菜单
        tracklist_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="曲目列表", menu=tracklist_menu)
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
        
        # 暂停按钮
        self.pause_btn = tk.Button(left_controls, text="⏸", 
                             bg='#f39c12', fg='white',
                             font=('Arial', 10),
                             relief=tk.RAISED, cursor='hand2',
                             width=2, height=1,
                             command=self.pause_music)
        self.pause_btn.pack(side=tk.LEFT, padx=8)
        
        # 停止按钮
        self.stop_btn = tk.Button(left_controls, text="⏹", 
                            bg='#e74c3c', fg='white',
                            font=('Arial', 10),
                            relief=tk.RAISED, cursor='hand2',
                            width=2, height=1,
                            command=self.stop_music)
        self.stop_btn.pack(side=tk.LEFT, padx=8)
        
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
        
        # # 进度条（带拖动块）
        # self.progress_var = tk.DoubleVar()
        # self.progress_scale = tk.Scale(progress_frame, from_=0, to=100, 
        #                               orient=tk.HORIZONTAL, 
        #                               variable=self.progress_var,
        #                               bg='#ecf0f1', highlightthickness=0,
        #                               showvalue=False,
        #                               command=self.on_progress_change)
        # self.progress_scale.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        # # 绑定进度条事件
        # self.progress_scale.bind('<ButtonPress-1>', self.on_progress_press)
        # self.progress_scale.bind('<ButtonRelease-1>', self.on_progress_release)
        
        # 总时间标签
        self.total_time_label = tk.Label(progress_frame, text="00:00", 
                                        bg='#ecf0f1', font=('微软雅黑', 10))
        self.total_time_label.pack(side=tk.LEFT, padx=5)
        
        # # 百分比标签
        # self.percent_label = tk.Label(progress_frame, text="0%", 
        #                              bg='#ecf0f1', font=('微软雅黑', 10), width=5)
        # self.percent_label.pack(side=tk.LEFT, padx=5)
        
        # 右侧：音量调节
        volume_frame = tk.Frame(control_frame, bg='#ecf0f1')
        volume_frame.pack(side=tk.RIGHT, padx=10)
               
        # 音量滑块
        self.volume_scale = tk.Scale(volume_frame, from_=0, to=100, 
                       orient=tk.HORIZONTAL, length=100,
                       bg='#ecf0f1', highlightthickness=0,
                       showvalue=0,          # 告诉 Tkinter 不要显示当前数值
                    #    tickinterval=20,    # 每隔20显示一个刻度数字 (0, 20, 40...)
                    #    resolution=1,       # 拖动一次改变1个数值
                       command=self.change_volume)
        self.volume_scale.set(80)
        self.volume_scale.pack(side=tk.LEFT)
        
    def create_main_content(self):
        """创建主要内容区域（使用PanedWindow实现可调整大小）"""
        # 创建水平PanedWindow
        self.main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 左侧：文件夹目录
        self.left_frame = tk.Frame(self.main_paned, bg='white', relief=tk.SUNKEN, borderwidth=1)
        # 👇 关键：禁止内部控件“挤扁”外层，保证初始有一点点可视宽度
        self.left_frame.pack_propagate(False)
        self.main_paned.add(self.left_frame, weight=1) # 左边占 1 份
        
        # 文件夹树形视图容器
        folder_container = tk.Frame(self.left_frame, bg='white')
        folder_container.pack(fill=tk.BOTH, expand=True)
        
        # 文件夹树形视图
        self.folder_tree = ttk.Treeview(folder_container, selectmode='browse')
        self.folder_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.folder_tree.heading('#0', text='文件夹', anchor='w')
        
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
        self.main_paned.add(self.right_frame, weight=8) # 右边占据 8 份（极大占比）
        
        # 创建垂直PanedWindow用于右侧上下分割
        self.right_paned = ttk.PanedWindow(self.right_frame, orient=tk.VERTICAL)
        self.right_paned.pack(fill=tk.BOTH, expand=True)
        
        # 顶部：播放列表按钮区域
        self.top_btn_frame = tk.Frame(self.right_paned, bg='#ecf0f1', height=35)
        self.top_btn_frame.pack_propagate(False)
        self.right_paned.add(self.top_btn_frame, weight=0)
        
        self.playlist_buttons = {}
        self.update_playlist_buttons()
        
        # 中间：舞曲编排表格
        self.top_frame = tk.Frame(self.right_paned, bg='white')
        self.right_paned.add(self.top_frame, weight=3) # 表格区域占 3份
        
        self.top_frame.grid_rowconfigure(0, weight=1)
        self.top_frame.grid_columnconfigure(0, weight=1)
        
        table_container = tk.Frame(self.top_frame, bg='white')
        table_container.grid(row=0, column=0, sticky='nsew')
        table_container.grid_rowconfigure(0, weight=1)
        table_container.grid_columnconfigure(0, weight=1)
        
        self.create_song_table_in_container(table_container)
        
        # 底部：音频控制
        self.bottom_frame = tk.Frame(self.right_paned, bg='white', relief=tk.GROOVE, borderwidth=1)
        # 👇 同样让外层保持一定初始高度
        self.bottom_frame.pack_propagate(False)
        self.right_paned.add(self.bottom_frame, weight=1) # 底部占 1 份
        
        audio_container = tk.Frame(self.bottom_frame, bg='white')
        audio_container.pack(fill=tk.BOTH, expand=True)
        
        self.create_audio_controls(audio_container)
        
        self.load_playlist(1)

    def create_song_table_in_container(self, container):
        """在指定容器中创建舞曲编排表格"""
        columns = ('序号', '播放时间', '歌名', '歌曲时长', '起始时间', 
                '播放时长', '停顿时长', '音量', '灯光')
        
        self.song_table = ttk.Treeview(container, columns=columns, show='headings', height=15)
        
        # 设置列标题
        for col in columns:
            self.song_table.heading(col, text=col)
        
        # 设置列宽
        self.song_table.column('序号', width=15, anchor='center')
        self.song_table.column('播放时间', width=50, anchor='center')
        self.song_table.column('歌名', width=570, anchor='w')
        self.song_table.column('歌曲时长', width=50, anchor='center')
        self.song_table.column('起始时间', width=50, anchor='center')
        self.song_table.column('播放时长', width=50, anchor='center')
        self.song_table.column('停顿时长', width=50, anchor='center')
        self.song_table.column('音量', width=30, anchor='center')
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
        # self.song_listbox.bind('<<ListboxSelect>>', self.on_song_select)
        self.song_table.bind('<Double-1>', self.on_table_double_click)
        self.song_table.bind('<Button-3>', self.show_table_context_menu)
        # self.song_table.bind('<ButtonPress-1>', self.on_drag_start)
        # self.song_table.bind('<ButtonRelease-1>', self.on_drag_end)
        # self.song_table.bind('<B1-Motion>', self.on_drag_motion)

    def create_audio_controls(self, container):
        """创建音频控制"""
        # 左：七段均衡器
        eq_frame = tk.Frame(container, bg='white', relief=tk.GROOVE, borderwidth=1)
        eq_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        # 👇 新增：为均衡器绑定右键菜单
        eq_frame.bind('<Button-3>', self.show_eq_context_menu)
                
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
            
            tk.Label(slider_frame, text=freq, bg='white', font=('微软雅黑', 8)).pack()
        
        # 中：音频调节
        tempo_frame = tk.Frame(container, bg='white', relief=tk.GROOVE, borderwidth=1)
        tempo_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        # 👇 新增：为音频调节绑定右键菜单
        tempo_frame.bind('<Button-3>', self.show_tempo_context_menu)

        # 节拍滑块 - 使用 ttk
        tk.Label(tempo_frame, text="节拍", bg='white').pack(anchor='c', pady=(0, 0))
        self.beat_slider = ttk.Scale(tempo_frame, from_=30, to=150,
                                    orient=tk.HORIZONTAL,
                                    command=self.on_beat_change)
        self.beat_slider.set(90)
        self.beat_slider.pack(pady=(0, 5), fill=tk.X, padx=5)

        # 速度滑块
        tk.Label(tempo_frame, text="速度", bg='white').pack(anchor='c', pady=(0, 0))
        self.speed_slider = ttk.Scale(tempo_frame, from_=50, to=150,
                                    orient=tk.HORIZONTAL,
                                    command=self.on_speed_change)
        self.speed_slider.set(100)
        self.speed_slider.pack(pady=(0, 5), fill=tk.X, padx=5)

        # 音调滑块
        tk.Label(tempo_frame, text="音调", bg='white').pack(anchor='c', pady=(0, 0))
        self.pitch_slider = ttk.Scale(tempo_frame, from_=-12, to=12,
                                    orient=tk.HORIZONTAL,
                                    command=self.on_pitch_change)
        self.pitch_slider.set(0)
        self.pitch_slider.pack(pady=(0, 5), fill=tk.X, padx=5)

        # 右：歌曲信息
        metadata_frame = tk.Frame(container, bg='white', relief=tk.GROOVE, borderwidth=1)
        metadata_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
                
        self.metadata_text = tk.Text(metadata_frame, font=('微软雅黑', 9), 
                                    bg='#f8f9fa', wrap=tk.WORD, height=15)
        self.metadata_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def show_eq_context_menu(self, event):
        """显示七段均衡器的右键菜单"""
        # 创建菜单
        eq_menu = tk.Menu(self.root, tearoff=0)
        eq_menu.add_command(label="重置均衡器", command=self.reset_eq)
        # 在鼠标右键点击的位置弹出菜单
        eq_menu.post(event.x_root, event.y_root)

    def show_tempo_context_menu(self, event):
        """显示音频调节的右键菜单"""
        # 创建菜单
        tempo_menu = tk.Menu(self.root, tearoff=0)
        tempo_menu.add_command(label="重置音频调节", command=self.reset_tempo)
        # 在鼠标右键点击的位置弹出菜单
        tempo_menu.post(event.x_root, event.y_root)

    def update_playlist_buttons(self):
        """更新播放列表按钮"""
        for widget in self.top_btn_frame.winfo_children():
            widget.destroy()
        
        colors = ['#3498db', '#2ecc71', '#e67e22', '#9b59b6', '#e74c3c']
        self.playlist_buttons = {}
        for i, (playlist_id, playlist_data) in enumerate(self.playlist_manager.playlists.items()):
            color = colors[i % len(colors)]
            btn = tk.Button(self.top_btn_frame, text=playlist_data["name"], 
                        bg=color, fg='white',
                        font=('微软雅黑', 10, 'bold'),
                        relief=tk.RAISED, cursor='hand2',
                        width=12, height=1,
                        command=lambda id=playlist_id: self.load_playlist(id))
            btn.pack(side=tk.LEFT, padx=5, pady=5)
            btn.bind('<Button-3>', lambda e, id=playlist_id: self.show_playlist_context_menu(e, id))
            self.playlist_buttons[playlist_id] = btn

    def create_status_bar(self):
        """创建底部状态栏"""
        self.status_frame = tk.Frame(self.root, bg='#2c3e50', height=30)
        self.status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_frame.pack_propagate(False)
        # 左侧：日期时间
        self.status_time_label = tk.Label(self.status_frame, text="", 
                                    bg='#2c3e50', fg='white',
                                    font=('微软雅黑', 9))
        self.status_time_label.pack(side=tk.LEFT, padx=5)

        # 播放模式
        self.status_play_mode_label = tk.Label(self.status_frame, text="播放模式: 顺序播放", 
                                            bg='#2c3e50', fg='#3498db',
                                            font=('微软雅黑', 10, 'bold'))
        self.status_play_mode_label.pack(side=tk.LEFT, padx=15)

        # 位置/序号
        self.status_position_label = tk.Label(self.status_frame, text="0/0", 
                                            bg='#2c3e50', fg='#e67e22',
                                            font=('微软雅黑', 10, 'bold'))
        self.status_position_label.pack(side=tk.LEFT, padx=5)

        # 已播时长/总时长
        self.status_time_display_label = tk.Label(self.status_frame, text="00:00 / 00:00", 
                                                bg='#2c3e50', fg='#2ecc71',
                                                font=('微软雅黑', 10))
        self.status_time_display_label.pack(side=tk.LEFT, padx=5)

        # 百分比标签（状态栏）
        self.percent_label = tk.Label(self.status_frame, text="0%", 
                                    bg='#2c3e50', fg='#e74c3c',
                                    font=('微软雅黑', 10, 'bold'), width=6)
        self.percent_label.pack(side=tk.LEFT, padx=5)

        # 右侧：状态信息
        self.status_label = tk.Label(self.status_frame, text="就绪", 
                                bg='#2c3e50', fg='white',
                                font=('微软雅黑', 10))

        self.status_label.pack(side=tk.RIGHT, padx=10)
        
        # 更新时间
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
        self.root.bind('<Delete>', lambda e: self.delete_selected())
        
    def setup_drag_drop(self):
        """设置拖放功能"""
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self.on_drop)
        except:
            pass
    
    # ==================== 进度条事件处理 ====================
    
    def on_progress_press(self, event):
        """进度条按下事件"""
        self.progress_dragging = True
    
    def on_progress_release(self, event):
        """进度条释放事件"""
        if self.progress_dragging and self.player.current_file:
            value = self.progress_var.get()
            total_length = self.player.get_length()
            if total_length > 0:
                position = (value / 100) * total_length
                self.player.set_position(position)
                self.status_label.config(text=f"跳转到: {self.format_time(position)}")
        self.progress_dragging = False
    
    def on_progress_change(self, value):
        """进度条值改变事件"""
        if self.player.current_file and self.progress_dragging:
            value_float = float(value)
            total_length = self.player.get_length()
            if total_length > 0:
                position = (value_float / 100) * total_length
                self.current_time_label.config(text=self.format_time(position))
                self.percent_label.config(text=f"{int(value_float)}%")
    
    # ==================== 音频控制事件 ====================
    
    def reset_eq(self):
        """重置均衡器"""
        for slider in self.eq_sliders:
            slider.set(0)
        self.status_label.config(text="均衡器已重置")
    
    def reset_tempo(self):
        """重置音频调节"""
        self.beat_slider.set(100)
        self.speed_slider.set(100)
        self.pitch_slider.set(0)
        self.status_label.config(text="音频调节已重置")
    
    def on_eq_change(self, index, value):
        """均衡器改变事件"""
        pass
    
    def on_beat_change(self, value):
        """节拍改变事件"""
        self.status_label.config(text=f"节拍: {round(float(value))}")
    
    def on_speed_change(self, value):
        """速度改变事件"""
        self.status_label.config(text=f"速度: {round(float(value))/100:.1f}")
    
    def on_pitch_change(self, value):
        """音调改变事件"""
        self.status_label.config(text=f"音调: {round(float(value))}")
    
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
    
    def scan_music_files(self, folder):
        """扫描文件夹中的音乐文件"""
        music_extensions = ['.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg']
        music_files = []
        for root, dirs, files in os.walk(folder):
            for file in files:
                if any(file.lower().endswith(ext) for ext in music_extensions):
                    music_files.append(os.path.join(root, file))
        return music_files
    
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
    
    def play_song_by_index(self, song_index):
        """根据索引播放歌曲（应用配置）"""
        songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
        if song_index < 0 or song_index >= len(songs):
            return
        
        # 设置播放列表
        self.player.playlist = songs
        
        # 应用播放模式
        if self.player.play_mode == "random":
            song_index = random.randint(0, len(songs) - 1)
        elif self.player.play_mode == "single_loop":
            # 单曲循环保持当前索引不变
            if self.player.current_index >= 0 and self.player.current_index < len(songs):
                song_index = self.player.current_index
        # sequential模式使用传入的索引
        
        # 设置当前索引
        self.player.current_index = song_index
        
        # 获取歌曲路径和配置
        file_path = songs[song_index]
        config = self.song_configs.get(file_path, {})

        # 获取歌曲配置
        start_time = config.get('start_time', 0)
        play_duration = config.get('play_duration', 0)
        volume = config.get('volume', self.player.volume)
        pause_duration = config.get('pause_duration', 0)
        
        # 设置音量
        self.player.set_volume(volume)
        self.volume_scale.set(volume)
        
        # 播放
        if self.player.play(file_path, start_pos=start_time):
            self.player.playlist = songs
            self.player.current_index = song_index
            self.status_label.config(text=f"正在播放: {os.path.basename(file_path)}")
            self.update_status_position()
            self.update_play_times()
            self.show_metadata(file_path)
            self.highlight_playing_song()
            
            # 如果设置了播放时长，启动定时器
            if play_duration > 0:
                self.start_play_duration_timer(play_duration)
            
            # 如果设置了停顿时长，启动停顿定时器
            if pause_duration > 0:
                self.start_pause_timer(pause_duration)
    
    def start_play_duration_timer(self, duration):
        """启动播放时长定时器"""
        def timer():
            time.sleep(duration)
            if self.player.is_playing:
                self.root.after(0, self.next_song)
        threading.Thread(target=timer, daemon=True).start()
    
    def start_pause_timer(self, duration):
        """启动停顿定时器"""
        def timer():
            time.sleep(duration)
            if self.player.is_playing:
                self.root.after(0, self.pause_music)
        threading.Thread(target=timer, daemon=True).start()
    
    def play_music(self):
        """播放音乐"""
        selection = self.song_table.selection()
        if selection:
            item = selection[0]
            values = self.song_table.item(item, 'values')
            song_index = int(values[0]) - 1
            self.play_song_by_index(song_index)
    
    def pause_music(self):
        """暂停音乐"""
        if self.player.is_playing:
            self.player.pause()
            self.status_label.config(text="暂停")
        elif self.player.is_paused:
            self.player.resume()
            self.status_label.config(text="继续播放")
    
    def stop_music(self):
        """停止音乐"""
        self.player.stop()
        self.status_label.config(text="停止播放")
        self.progress_bar['value'] = 0
        self.current_time_label.config(text="00:00")
        self.percent_label.config(text="0%")
        self.status_position_label.config(text="0/0")
        self.status_time_display_label.config(text="00:00 / 00:00")
        
    def previous_song(self):
        """上一首"""
        songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
        if not songs:
            return
        
        self.player.playlist = songs
        if self.player.current_index < 0:
            self.player.current_index = 0
        
        self.player.current_index = (self.player.current_index - 1) % len(songs)
        self.play_song_by_index(self.player.current_index)
    
    def next_song(self):
        """下一首（自动播放）"""
        songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
        if not songs:
            return
        
        self.player.playlist = songs
        
        if self.player.play_mode == "random":
            self.player.current_index = random.randint(0, len(songs) - 1)
        elif self.player.play_mode == "single_loop":
            if self.player.current_index < 0:
                self.player.current_index = 0
        else:  # sequential
            self.player.current_index = (self.player.current_index + 1) % len(songs)
        
        self.play_song_by_index(self.player.current_index)
    
    def highlight_playing_song(self):
        """高亮当前播放的歌曲"""
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
        volume = int(float(value))
        self.player.set_volume(volume)
        
        if self.player.current_file:
            if self.player.current_file not in self.song_configs:
                self.song_configs[self.player.current_file] = {}
            self.song_configs[self.player.current_file]['volume'] = volume

    def on_progress_drag(self, value):
        """进度条拖动事件"""
        if self.player.current_file:
            total_length = self.player.get_length()
            if total_length > 0:
                position = (float(value) / 100) * total_length
                self.player.set_position(position)
                # 更新播放状态
                self.player.is_playing = True
                self.player.is_paused = False
                self.status_time_display_label.config(text=f"{self.format_time(position)} / {self.format_time(total_length)}")

    def update_progress_thread(self):
        """更新进度条线程"""
        def update():
            while True:
                if self.player.is_playing and not self.progress_dragging:
                    try:
                        current_pos = self.player.get_position()
                        total_length = self.player.current_length  # 使用缓存的时长
                        
                        if total_length > 0:
                            progress = (current_pos / total_length) * 100
                            if progress <= 100:
                                self.root.after(0, self.update_progress_bar, 
                                            current_pos, total_length, progress)
                            
                            # 检查是否播放完毕，自动播放下一首
                            if current_pos >= total_length and current_pos > 0:
                                self.root.after(0, self.next_song)
                    except Exception as e:
                        print(f"进度更新错误: {e}")
                
                time.sleep(0.5)  
        
        thread = threading.Thread(target=update, daemon=True)
        thread.start()    

    def update_progress_bar(self, current_pos, total_length, progress):
        """更新进度条"""
        if not self.progress_dragging:
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
        """加载指定播放列表"""
        self.current_playlist = playlist_num
        playlist_data = self.playlist_manager.playlists[playlist_num]
        
        # 清空歌曲列表
        # self.song_listbox.delete(0, tk.END)
        
        # 更新当前播放列表标签
        # self.current_playlist_label.config(text=f"当前: {playlist_data['name']}")
        
        # 清空表格
        for item in self.song_table.get_children():
            self.song_table.delete(item)
        
        # 添加歌曲到列表
        for song in playlist_data["songs"]:
            song_name = os.path.basename(song)
            # self.song_listbox.insert(tk.END, song_name)
        
        # 更新表格
        self.update_song_table(playlist_data["songs"])
        
        # 高亮当前播放列表按钮
        for id, btn in self.playlist_buttons.items():
            if id == playlist_num:
                btn.config(relief=tk.SUNKEN)
            else:
                btn.config(relief=tk.RAISED)
        
        self.status_label.config(text=f"已切换到: {playlist_data['name']}")
        self.update_status_position()
        self.update_play_times()
    
    def update_song_table(self, songs):
        """更新歌曲表格"""
        for i, song_path in enumerate(songs, 1):
            song_name = os.path.basename(song_path)
            duration_seconds = self.get_audio_duration_seconds(song_path)
            duration_str = self.format_time(duration_seconds)
            
            config = self.song_configs.get(song_path, {})
            start_time = config.get('start_time', self.default_settings['start_time'])
            play_duration = config.get('play_duration', duration_seconds if not self.default_settings['play_duration'] else self.default_settings['play_duration'])
            pause_duration = config.get('pause_duration', self.default_settings['pause_duration'])
            volume = config.get('volume', self.default_settings['volume'])
            light = config.get('light', '')
            
            play_time = self.calculate_play_time(i, songs)
            
            row = (
                str(i),
                play_time,
                song_name,
                duration_str,
                self.format_time(start_time),
                self.format_time(play_duration),
                self.format_time(pause_duration),
                str(volume),
                light
            )
            self.song_table.insert('', 'end', values=row)
    
    def calculate_play_time(self, index, songs):
        """计算预计播放时间"""
        now = datetime.datetime.now()
        total_seconds = 0
        
        current_index = self.player.current_index if self.player.current_index >= 0 else -1
        
        if current_index >= 0 and current_index < index - 1:
            for i in range(current_index, index - 1):
                if i < len(songs):
                    duration = self.get_audio_duration_seconds(songs[i])
                    config = self.song_configs.get(songs[i], {})
                    pause_duration = config.get('pause_duration', 0)
                    total_seconds += duration + pause_duration
            
            play_time = now + datetime.timedelta(seconds=total_seconds)
            return play_time.strftime("%H:%M")
        elif current_index == index - 1:
            return now.strftime("%H:%M")
        else:
            return ""
    
    def update_play_times(self):
        """更新所有歌曲的播放时间"""
        songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
        items = self.song_table.get_children()
        
        for i, item in enumerate(items, 1):
            values = list(self.song_table.item(item, 'values'))
            values[1] = self.calculate_play_time(i, songs)
            self.song_table.item(item, values=values)
    
    def get_audio_duration_seconds(self, file_path):
        """获取音频时长（秒）"""
        # 首先检查缓存
        if hasattr(self.player, '_length_cache') and file_path in self.player._length_cache:
            return self.player._length_cache[file_path]
        
        try:
            sound = pygame.mixer.Sound(file_path)
            duration = sound.get_length()
            # 存入缓存
            if hasattr(self.player, '_length_cache'):
                self.player._length_cache[file_path] = duration
            return duration
        except:
            try:
                sound = pygame.mixer.Sound(file_path)
                duration = sound.get_length()
                return duration
            except:
                try:
                    import mutagen
                    audio = mutagen.File(file_path)
                    if audio and hasattr(audio, 'info'):
                        return audio.info.length
                except:
                    pass
            return 0
    
    def add_song_to_current_playlist(self, song_path):
        """添加歌曲到当前播放列表"""
        return self.playlist_manager.add_song(self.current_playlist, song_path)
    
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
    
    def show_playlist_context_menu(self, event, playlist_id):
        """显示播放列表右键菜单"""
        context_menu = tk.Menu(self.root, tearoff=0)
        context_menu.add_command(label="加载列表", command=lambda: self.load_playlist(playlist_id))
        context_menu.add_separator()
        context_menu.add_command(label="重命名", command=lambda: self.rename_playlist_by_id(playlist_id))
        if playlist_id != 1:
            context_menu.add_command(label="删除", command=lambda: self.delete_playlist_by_id(playlist_id))
        context_menu.add_separator()
        context_menu.add_command(label="重置该列表所有歌曲配置", 
                                command=lambda: self.reset_playlist_configs(playlist_id))
        context_menu.post(event.x_root, event.y_root)
    
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
                # 显示搜索结果
                self.song_table.delete(*self.song_table.get_children())
                for i, (playlist_id, song) in enumerate(results, 1):
                    song_name = os.path.basename(song)
                    duration_seconds = self.get_audio_duration_seconds(song)
                    duration_str = self.format_time(duration_seconds)
                    
                    config = self.song_configs.get(song, {})
                    start_time = config.get('start_time', 0)
                    play_duration = config.get('play_duration', duration_seconds)
                    pause_duration = config.get('pause_duration', 0)
                    volume = config.get('volume', 70)
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
                        light
                    )
                    self.song_table.insert('', 'end', values=row)
                
                self.status_label.config(text=f"找到 {len(results)} 个结果")
            else:
                messagebox.showinfo("搜索", "未找到匹配的歌曲")
    
    # ==================== 灯光控制功能 ====================
    
    def show_light_control(self):
        """显示灯光控制窗口"""
        light_window = tk.Toplevel(self.root)
        light_window.title("灯光控制")
        light_window.geometry("400x500")
        
        # 灯光模式
        modes = ["关闭", "常亮", "闪烁", "渐变", "音乐同步"]
        self.light_mode_var = tk.StringVar(value="关闭")
        
        tk.Label(light_window, text="灯光模式:", font=('微软雅黑', 12)).pack(pady=10)
        for mode in modes:
            tk.Radiobutton(light_window, text=mode, variable=self.light_mode_var, 
                          value=mode, font=('微软雅黑', 10)).pack(anchor='w', padx=20)
        
        # 灯光颜色
        tk.Label(light_window, text="灯光颜色:", font=('微软雅黑', 12)).pack(pady=10)
        colors_frame = tk.Frame(light_window)
        colors_frame.pack()
        for color in ['红色', '绿色', '蓝色', '白色', '多彩']:
            tk.Button(colors_frame, text=color, width=8, 
                     command=lambda c=color: self.set_light_color(c)).pack(side=tk.LEFT, padx=5)
        
        # 亮度控制
        tk.Label(light_window, text="亮度:", font=('微软雅黑', 12)).pack(pady=10)
        brightness_scale = tk.Scale(light_window, from_=0, to=100, orient=tk.HORIZONTAL)
        brightness_scale.set(50)
        brightness_scale.pack()
    
    def set_light_color(self, color):
        """设置灯光颜色"""
        self.status_label.config(text=f"灯光颜色: {color}")
    
    # ==================== 设置功能 ====================
    
    def show_settings(self):
        """显示设置窗口"""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("设置")
        settings_window.geometry("300x500")
        settings_window.transient(self.root)
        settings_window.grab_set()
        
        # # 歌库目录设置
        # tk.Label(settings_window, text="歌库目录:", font=('微软雅黑', 12)).pack(pady=5)
        # tk.Button(settings_window, text="选择目录", command=self.set_library_dir).pack(pady=5)
        
        # 默认设置
        tk.Label(settings_window, text="默认歌曲设置:", font=('微软雅黑', 12, 'bold')).pack(pady=10)
        
        # 默认起始时间
        tk.Label(settings_window, text="默认起始时间(秒):").pack()
        self.default_start_time_var = tk.StringVar(value=str(self.default_settings['start_time']))
        tk.Entry(settings_window, textvariable=self.default_start_time_var, width=20).pack(pady=5)
        
        # 默认播放时长
        tk.Label(settings_window, text="默认播放时长(秒, 0=完整):").pack()
        self.default_play_duration_var = tk.StringVar(value=str(self.default_settings['play_duration']))
        tk.Entry(settings_window, textvariable=self.default_play_duration_var, width=20).pack(pady=5)
        
        # 默认停顿时长
        tk.Label(settings_window, text="默认停顿时长(秒):").pack()
        self.default_pause_duration_var = tk.StringVar(value=str(self.default_settings['pause_duration']))
        tk.Entry(settings_window, textvariable=self.default_pause_duration_var, width=20).pack(pady=5)
        
        # 默认音量
        tk.Label(settings_window, text="默认音量(0-100):").pack()
        self.default_volume_var = tk.StringVar(value=str(self.default_settings['volume']))
        tk.Entry(settings_window, textvariable=self.default_volume_var, width=20).pack(pady=5)
        
        # 滑音参数
        tk.Label(settings_window, text="滑音参数(秒):").pack()
        self.fade_out_duration_var = tk.StringVar(value=str(self.default_settings['fade_out_duration']))
        tk.Entry(settings_window, textvariable=self.fade_out_duration_var, width=20).pack(pady=5)

        # # 自动播放
        # auto_play_var = tk.BooleanVar(value=False)
        # tk.Checkbutton(settings_window, text="启动时自动播放", 
        #         variable=auto_play_var).pack(pady=10)

        
        # 保存按钮
        def save_settings():
            try:
                self.default_settings['start_time'] = float(self.default_start_time_var.get())
                self.default_settings['play_duration'] = float(self.default_play_duration_var.get())
                self.default_settings['pause_duration'] = float(self.default_pause_duration_var.get())
                self.default_settings['volume'] = int(self.default_volume_var.get())
                self.default_settings['fade_out_duration'] = float(self.fade_out_duration_var.get())
                
                # 应用滑音参数
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
    
    def show_shortcut_settings(self):
        """显示快捷键设置"""
        messagebox.showinfo("快捷键设置", "快捷键列表:\n\n"
                          "Ctrl+O: 打开文件\n"
                          "Ctrl+Shift+O: 打开文件夹\n"
                          "Ctrl+F: 搜索\n"
                          "Space: 播放/暂停\n"
                          "Left: 上一首\n"
                          "Right: 下一首\n"
                          "F2: 减少音量\n"
                          "F3: 增加音量\n\n"
                          "Delete: 删除选中项\n")
    
    def set_play_mode(self, mode):
        """设置播放模式"""
        self.player.play_mode = mode
        mode_names = {"sequential": "顺序播放", "single_loop": "单曲循环", "random": "随机播放"}
        self.status_play_mode_label.config(text=f"播放模式: {mode_names[mode]}")
        self.status_label.config(text=f"播放模式: {mode_names[mode]}")
        
        # 更新菜单显示
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
        
        dialog = tk.Toplevel(self.root)
        dialog.title(f"编辑歌曲: {os.path.basename(song_path)}")
        dialog.geometry("300x250")
        dialog.transient(self.root)
        dialog.grab_set()
        
        edit_frame = tk.Frame(dialog)
        edit_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        tk.Label(edit_frame, text="起始时间(秒):").grid(row=0, column=0, sticky='w', pady=5)
        start_time_var = tk.StringVar(value=str(config.get('start_time', 0)))
        tk.Entry(edit_frame, textvariable=start_time_var, width=20).grid(row=0, column=1, pady=5)
        
        tk.Label(edit_frame, text="播放时长(秒):").grid(row=1, column=0, sticky='w', pady=5)
        play_duration_var = tk.StringVar(value=str(int(config.get('play_duration', self.get_audio_duration_seconds(song_path)))))
        tk.Entry(edit_frame, textvariable=play_duration_var, width=20).grid(row=1, column=1, pady=5)
        
        tk.Label(edit_frame, text="停顿时长(秒):").grid(row=2, column=0, sticky='w', pady=5)
        pause_duration_var = tk.StringVar(value=str(config.get('pause_duration', 0)))
        tk.Entry(edit_frame, textvariable=pause_duration_var, width=20).grid(row=2, column=1, pady=5)
        
        tk.Label(edit_frame, text="音量(0-100):").grid(row=3, column=0, sticky='w', pady=5)
        volume_var = tk.StringVar(value=str(config.get('volume', 70)))
        tk.Entry(edit_frame, textvariable=volume_var, width=20).grid(row=3, column=1, pady=5)
        
        tk.Label(edit_frame, text="灯光:").grid(row=4, column=0, sticky='w', pady=5)
        light_var = tk.StringVar(value=str(config.get('light', '')))
        tk.Entry(edit_frame, textvariable=light_var, width=20).grid(row=4, column=1, pady=5)
        
        button_frame = tk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        
        def save_config():
            try:
                new_config = {
                    'start_time': float(start_time_var.get()),
                    'play_duration': int(float(play_duration_var.get())),
                    'pause_duration': float(pause_duration_var.get()),
                    'volume': int(volume_var.get()),
                    'light': light_var.get()
                }
                self.song_configs[song_path] = new_config
                self.load_playlist(self.current_playlist)
                # dialog.destroy()  # 删除这行，保存后不关闭窗口
                self.status_label.config(text="歌曲配置已保存")
                save_button.config(text="已保存", bg='#27ae60')  # 按钮变绿提示已保存
                dialog.after(1000, lambda: save_button.config(text="保存", bg='#2ecc71'))  # 1秒后恢复                

            except ValueError:
                messagebox.showerror("错误", "请输入有效的数字")
        
        def prev_song():
            if song_index > 0:
                self.song_table.selection_set(self.song_table.get_children()[song_index - 1])
                dialog.destroy()
                self.show_song_edit_dialog()
        
        def next_song():
            if song_index < len(songs) - 1:
                self.song_table.selection_set(self.song_table.get_children()[song_index + 1])
                dialog.destroy()
                self.show_song_edit_dialog()
        
        tk.Button(button_frame, text="上一曲", command=prev_song, 
                 bg='#3498db', fg='white', width=10).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="下一曲", command=next_song,
                 bg='#3498db', fg='white', width=10).pack(side=tk.LEFT, padx=5)
        # tk.Button(button_frame, text="保存", command=save_config,
                #  bg='#2ecc71', fg='white', width=10).pack(side=tk.LEFT, padx=5)
        save_button = tk.Button(button_frame, text="保存", command=save_config,
                bg='#2ecc71', fg='white', width=10)
        save_button.pack(side=tk.LEFT, padx=5)        
    
    def on_drag_start(self, event):
        """开始拖动"""
        item = self.song_table.identify_row(event.y)
        if item:
            self.drag_item = item
            self.song_table.selection_set(item)
    
    def on_drag_motion(self, event):
        """拖动中"""
        if self.drag_item:
            target = self.song_table.identify_row(event.y)
            if target and target != self.drag_item:
                self.song_table.move(self.drag_item, '', self.song_table.index(target))
                self.drag_item = target
    
    def on_drag_end(self, event):
        """结束拖动"""
        if self.drag_item:
            items = self.song_table.get_children()
            songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
            new_songs = []
            
            for item in items:
                values = self.song_table.item(item, 'values')
                song_index = int(values[0]) - 1
                if song_index < len(songs):
                    new_songs.append(songs[song_index])
            
            self.playlist_manager.playlists[self.current_playlist]["songs"] = new_songs
            self.playlist_manager.save_playlists()
            self.drag_item = None
            self.load_playlist(self.current_playlist)
    
    def on_table_double_click(self, event):
        """表格双击事件 - 双击任意位置从头播放"""
        item = self.song_table.identify_row(event.y)
        if item:
            self.song_table.selection_set(item)
            values = self.song_table.item(item, 'values')
            song_index = int(values[0]) - 1
            # 从头播放
            self.play_song_by_index(song_index)
    
    def update_status_position(self):
        """更新当前播放位置信息"""
        if self.player.current_index >= 0:
            total = len(self.playlist_manager.playlists[self.current_playlist]["songs"])
            self.status_position_label.config(text=f"{self.player.current_index + 1}/{total}")
        else:
            self.status_position_label.config(text="0/0")

    def get_bpm(self, file_path):
        """使用多种方法检测 BPM，取平均值"""
        try:
            import numpy as np
            
            # 加载音频文件
            y, sr = librosa.load(file_path, sr=22050)
            
            bpm_values = []
            
            # 方法1：标准方法
            try:
                tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
                if isinstance(tempo, np.ndarray):
                    tempo = tempo[0]
                bpm_values.append(float(tempo))
            except:
                pass
            
            # 方法2：使用 onset strength
            try:
                onset_env = librosa.onset.onset_strength(y=y, sr=sr)
                tempo = librosa.feature.rhythm.tempo(onset_envelope=onset_env, sr=sr)
                if isinstance(tempo, np.ndarray):
                    tempo = tempo[0]
                bpm_values.append(float(tempo))
            except:
                pass
            
            # 方法3：调整参数
            try:
                tempo, _ = librosa.beat.beat_track(y=y, sr=sr, hop_length=256)
                if isinstance(tempo, np.ndarray):
                    tempo = tempo[0]
                bpm_values.append(float(tempo))
            except:
                pass
            
            # 计算平均值
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
                # 缓存结果
                self.bpm_cache[file_path] = bpm
                
                # 在主线程中更新 UI
                if hasattr(self, 'metadata_text') and self.metadata_text.winfo_exists():
                    self.metadata_text.after(0, self.update_bpm_display, bpm)
            except Exception as e:
                print(f"BPM 检测出错: {e}")
        
        # 创建并启动后台线程
        thread = threading.Thread(target=detect_and_update, daemon=True)
        self.bpm_threads[file_path] = thread
        thread.start()
    
    def update_bpm_display(self, bpm):
        """更新 BPM 显示"""
        try:
            # 获取当前显示的内容
            current_text = self.metadata_text.get('1.0', tk.END)
            
            # 查找并替换 BPM 行
            lines = current_text.split('\n')
            updated_lines = []
            for line in lines:
                if line.startswith("BPM:"):
                    updated_lines.append(f"BPM: {bpm}")
                else:
                    updated_lines.append(line)
            
            # 更新显示
            self.metadata_text.delete('1.0', tk.END)
            self.metadata_text.insert('1.0', '\n'.join(updated_lines))
        except Exception as e:
            print(f"更新 BPM 显示出错: {e}")

    def show_metadata(self, file_path):
        """显示歌曲元数据信息"""
        try:
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            duration = self.get_audio_duration_seconds(file_path)
            
            if file_size < 1024:
                size_str = f"{file_size} B"
            elif file_size < 1024 * 1024:
                size_str = f"{file_size / 1024:.1f} KB"
            else:
                size_str = f"{file_size / (1024 * 1024):.1f} MB"

            # 获取音频文件的扩展名
            file_ext = os.path.splitext(file_path)[1].lower()
            
            # 初始化音频信息变量
            bitrate = "N/A"
            sample_rate = "N/A"
            channels = "N/A"
            bit_depth = "N/A"
            bpm = "N/A"
            
            # 使用 mutagen 读取音频元数据
            try:
                if file_ext == '.mp3':
                    audio = MP3(file_path)
                    if hasattr(audio.info, 'bitrate'):
                        bitrate = f"{audio.info.bitrate / 1000:.0f} kbps"
                    if hasattr(audio.info, 'sample_rate'):
                        sample_rate = f"{audio.info.sample_rate} Hz"
                    if hasattr(audio.info, 'channels'):
                        channels = audio.info.channels
                    # MP3 通常没有 bit depth
                    bit_depth = "N/A"
                    
                    # 尝试获取 BPM
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
                    
                    # 尝试获取 BPM
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
                    bit_depth = "N/A"  # OGG Vorbis 通常没有 bit depth
                    
                    # 尝试获取 BPM
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

            # 使用 librosa 检测 BPM
            bpm = self.get_bpm(file_path)

            # mod_time = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
            
            # 构建元数据字符串            
            metadata = f"文件名: {file_name}\n"
            metadata += f"文件大小: {size_str}\n"
            # metadata += f"时长: {self.format_time(duration)}\n"
            # metadata += f"格式: {os.path.splitext(file_path)[1][1:].upper()}\n"
            # metadata += f"修改时间: {mod_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            # metadata += f"路径: {file_path}\n"
            # metadata += f"格式: {file_ext[1:].upper()}\n"
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
                          "版本: 1.0.0\n"
                          "作者: 魅影制作\n"
                          "版权: © 2026")
    
    def show_help(self):
        """显示帮助"""
        messagebox.showinfo("帮助", "使用说明:\n\n"
                          "1. 单击或拖拽文件到窗口快速添加\n"
                          "2. 双击歌曲行播放歌曲\n"
                          "3. 点击停止按钮可重头播放歌曲\n"
                          "4. 使用空格键播放/暂停\n"
                          "5. 使用左右方向键切换上一首/下一首\n"
                          "6. F2减少音量，F3增加音量\n"
                          "7. 右键点击表格可编辑歌曲参数\n"
                          "8. 右键播放列表可重置该列表所有歌曲配置")
    
    def check_updates(self):
        """检查更新"""
        messagebox.showinfo("检查更新", "当前已是最新版本")


if __name__ == "__main__":
    # 尝试使用tkinterdnd2（如果可用）
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except:
        root = tk.Tk()
    
    app = DanceMusicPlayer(root)

    # 在 app 创建之后设置图标，tkinterdnd2其底层实现可能对窗口初始化有特殊处理。
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
    if os.path.exists(icon_path):
        root.iconbitmap(icon_path)
        root.update_idletasks()  # 强制更新窗口

    root.mainloop()