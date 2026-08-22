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


class VUMeter(tk.Canvas):
    """VU表控件类"""
    def __init__(self, parent, width=30, height=150, bg='#1a1a2e', **kwargs):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0, **kwargs)
        self.width = width
        self.height = height
        self.level = 0.0  # 当前电平值 0.0-1.0
        self.peak_level = 0.0  # 峰值电平
        self.peak_hold_time = 0  # 峰值保持时间
        self._draw_vu()
    
    def _draw_vu(self):
        """绘制VU表"""
        self.delete("all")
        
        # 计算绘制区域
        margin = 5
        bar_width = self.width - 2 * margin
        bar_height = self.height - 2 * margin
        
        # 绘制背景
        self.create_rectangle(margin, margin, margin + bar_width, margin + bar_height,
                            fill='#2a2a3e', outline='#3a3a4e', width=1)
        
        # 绘制刻度线
        num_ticks = 10
        for i in range(num_ticks + 1):
            y = margin + bar_height - (i * bar_height / num_ticks)
            tick_width = 5 if i % 2 == 0 else 3
            self.create_line(margin, y, margin + tick_width, y, fill='#666666', width=1)
            
            # 添加刻度标签
            if i % 2 == 0:
                value = int(i * 10)
                self.create_text(margin + bar_width + 5, y, text=str(value), 
                               fill='#888888', font=('Arial', 6), anchor='w')
        
        # 绘制电平条（从下往上）
        if self.level > 0:
            level_height = bar_height * self.level
            level_y1 = margin + bar_height - level_height
            level_y2 = margin + bar_height
            
            # 根据电平选择颜色
            if self.level < 0.6:
                color = '#00ff00'  # 绿色
            elif self.level < 0.8:
                color = '#ffff00'  # 黄色
            else:
                color = '#ff0000'  # 红色
            
            # 绘制渐变效果
            for y in range(int(level_y1), int(level_y2)):
                progress = (y - level_y1) / max(1, (level_y2 - level_y1))
                if progress < 0.6:
                    color = self._get_gradient_color(progress / 0.6, (0, 255, 0), (255, 255, 0))
                else:
                    color = self._get_gradient_color((progress - 0.6) / 0.4, (255, 255, 0), (255, 0, 0))
                self.create_line(margin + 2, y, margin + bar_width - 2, y, fill=color)
        
        # 绘制峰值指示器
        if self.peak_level > 0:
            peak_y = margin + bar_height - (bar_height * self.peak_level)
            self.create_line(margin, peak_y, margin + bar_width, peak_y, 
                           fill='#ffffff', width=2)
    
    def _get_gradient_color(self, progress, color1, color2):
        """获取渐变色"""
        # 确保progress在0-1范围内
        progress = max(0.0, min(1.0, progress))
        r1, g1, b1 = color1
        r2, g2, b2 = color2
        
        r = int(r1 + (r2 - r1) * progress)
        g = int(g1 + (g2 - g1) * progress)
        b = int(b1 + (b2 - b1) * progress)
        
        # 确保RGB值在0-255范围内
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))
        
        return f'#{r:02x}{g:02x}{b:02x}'
    
    def set_level(self, level):
        """设置电平值"""
        self.level = max(0.0, min(1.0, level))
        
        # 更新峰值
        if self.level > self.peak_level:
            self.peak_level = self.level
            self.peak_hold_time = time.time()
        
        # 峰值保持1秒后下降
        if time.time() - self.peak_hold_time > 1.0:
            self.peak_level = max(0.0, self.peak_level - 0.02)
        
        self._draw_vu()


class MusicPlayerCore:
    """音乐播放核心类"""
    def __init__(self):
        super().__init__()
        # 优化音频初始化
        pygame.mixer.pre_init(44100, -16, 2, 4096)
        pygame.mixer.init()
        pygame.mixer.music.set_volume(0.8)
        self.current_file = None
        self.current_processed_file = None
        self.is_playing = False
        self.is_paused = False
        self.volume = 80
        self.play_mode = "sequential"  # sequential, single_loop, random
        self.current_position = 0
        self.playlist = []
        self.current_index = -1
        self.fade_in_duration = 2   # 滑入参数（秒）
        self.fade_out_duration = 3  # 滑出参数（秒）
        self._fade_thread = None
        self._stop_fade = False
        self.current_length = 0  # 缓存当前歌曲时长
        self._length_cache = {}  # 所有歌曲时长缓存
        self._fade_lock = threading.Lock()
        self._auto_next_timer = None
        self._temp_dir = os.path.join(tempfile.gettempdir(), "music_player_temp")
        self._ensure_temp_dir()
        self._audio_data = None  # 存储音频数据用于VU表
        self._audio_pos = 0  # 当前音频数据位置

    def _ensure_temp_dir(self):
        """确保临时目录存在"""
        if not os.path.exists(self._temp_dir):
            os.makedirs(self._temp_dir)

    def _get_temp_file_path(self, original_path, speed, pitch):
        """根据原始文件路径和参数生成临时文件路径"""
        param_str = f"{original_path}_{speed:.2f}_{pitch:.1f}"
        hash_str = hashlib.md5(param_str.encode()).hexdigest()[:12]
        return os.path.join(self._temp_dir, f"processed_{hash_str}.wav")

    def _apply_audio_effects(self, file_path, speed=1.0, pitch=0):
        """应用音频效果，返回处理后的文件路径"""
        try:
            # 如果速度和音调都是默认值，直接返回原文件
            if abs(speed - 1.0) < 0.01 and abs(pitch) < 0.01:
                return file_path, False
            
            # 生成临时文件路径
            temp_file = self._get_temp_file_path(file_path, speed, pitch)
            
            # 如果临时文件已存在，直接使用
            if os.path.exists(temp_file):
                print(f"使用缓存的临时文件: {temp_file}")
                return temp_file, True
            
            print(f"处理音频: {os.path.basename(file_path)}, 速度={speed}x, 音调={pitch}半音")
            
            # 加载音频
            y, sr = librosa.load(file_path, sr=None)
            
            # 应用速度变化
            if abs(speed - 1.0) > 0.01:
                y = librosa.effects.time_stretch(y, rate=speed)
            
            # 应用音调变化
            if abs(pitch) > 0.01:
                y = librosa.effects.pitch_shift(y, sr=sr, n_steps=pitch)
            
            # 保存处理后的音频
            sf.write(temp_file, y, sr)
            print(f"已生成临时文件: {temp_file}")
            
            return temp_file, True
            
        except Exception as e:
            print(f"音频处理失败: {e}")
            import traceback
            traceback.print_exc()
            return file_path, False

    def load(self, file_path):
        """加载音乐文件"""
        try:
            pygame.mixer.music.load(file_path)
            # 加载音频数据用于VU表
            self._load_audio_data(file_path)
            return True
        except Exception as e:
            print(f"加载失败: {e}")
            return False
    
    def _load_audio_data(self, file_path):
        """加载音频数据用于VU表"""
        try:
            # 使用librosa加载音频数据
            y, sr = librosa.load(file_path, sr=22050, mono=False)
            
            # 如果是单声道，复制为双声道
            if len(y.shape) == 1:
                y = np.stack([y, y])
            
            self._audio_data = y
            self._audio_pos = 0
            self._audio_sr = sr
            print(f"音频数据加载成功: {y.shape}, 采样率: {sr}")
        except Exception as e:
            print(f"加载音频数据失败: {e}")
            self._audio_data = None
    
    def get_audio_levels(self):
        """获取当前音频电平数据"""
        if self._audio_data is None:
            return 0.0, 0.0
        
        try:
            # 获取当前播放位置对应的音频数据
            current_pos = self.get_position()
            sample_pos = int(current_pos * self._audio_sr)
            
            # 确保位置有效
            if sample_pos >= self._audio_data.shape[1]:
                return 0.0, 0.0
            
            # 获取一小段音频数据
            window_size = 1024
            end_pos = min(sample_pos + window_size, self._audio_data.shape[1])
            
            if end_pos <= sample_pos:
                return 0.0, 0.0
            
            left_channel = self._audio_data[0, sample_pos:end_pos]
            right_channel = self._audio_data[1, sample_pos:end_pos] if self._audio_data.shape[0] > 1 else left_channel
            
            # 计算RMS电平
            left_rms = np.sqrt(np.mean(left_channel ** 2))
            right_rms = np.sqrt(np.mean(right_channel ** 2))
            
            # 转换为dB并映射到0-1范围
            left_level = self._rms_to_level(left_rms)
            right_level = self._rms_to_level(right_rms)
            
            return left_level, right_level
            
        except Exception as e:
            print(f"获取音频电平失败: {e}")
            return 0.0, 0.0
    
    def _rms_to_level(self, rms):
        """将RMS值转换为电平值(0-1)"""
        if rms < 0.00001:
            return 0.0
        
        # 使用对数刻度映射
        db = 20 * np.log10(rms)

        # 映射范围：-60dB到0dB
        level = (db + 60) / 60
        return max(0.0, min(1.0, level))
    
    def _fade_volume(self, from_vol, to_vol, duration, stop_event=None):
        """通用滑音方法：在指定时间内从from_vol渐变到to_vol"""
        steps = int(duration * 10)  # 每0.1秒一步
        if steps <= 0:
            steps = 1
        
        vol_step = (to_vol - from_vol) / steps
        
        for i in range(steps):
            if stop_event and stop_event.is_set():
                break
            current_vol = from_vol + vol_step * (i + 1)
            pygame.mixer.music.set_volume(max(0, min(100, current_vol)) / 100)
            time.sleep(0.1)
        
        # 确保最终音量正确
        pygame.mixer.music.set_volume(max(0, min(100, to_vol)) / 100)
    
    def play(self, file_path=None, start_pos=0, speed=1.0, pitch=0):
        """播放音乐（带滑入效果，支持变速变调）"""
        try:
            # 取消之前的自动下一首定时器
            self.cancel_auto_next()
            
            # 停止当前播放
            self._hard_stop()
            time.sleep(0.05)
            
            if file_path:
                self.current_file = file_path
                # 应用音频效果
                processed_file, is_temp = self._apply_audio_effects(file_path, speed, pitch)
                self.current_processed_file = processed_file if is_temp else None
            elif not self.current_file:
                return False
            
            # 确定实际播放的文件
            actual_file = self.current_processed_file or self.current_file
            
            # 加载文件
            if not self.load(actual_file):
                return False
            
            # 从缓存获取时长
            if self.current_file in self._length_cache:
                self.current_length = self._length_cache[self.current_file]
            else:
                self.current_length = self._get_file_length(actual_file)
                self._length_cache[self.current_file] = self.current_length
            
            # 设置初始音量为0（用于滑入）
            pygame.mixer.music.set_volume(0)
            
            # 播放
            # print(f"播放: {os.path.basename(actual_file)}, 起始: {start_pos}秒, 速度: {speed}x, 音调: {pitch}")
            if start_pos > 0:
                pygame.mixer.music.play(start=start_pos)
            else:
                pygame.mixer.music.play()
            
            self.is_playing = True
            self.is_paused = False
            
            # 启动滑入线程
            self._start_fade_in()
            return True
        except Exception as e:
            print(f"播放失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _get_file_length(self, file_path):
        """获取文件时长"""
        try:
            sound = pygame.mixer.Sound(file_path)
            length = sound.get_length()
            return length
        except:
            try:
                audio = mutagen.File(file_path)
                if audio and hasattr(audio, 'info'):
                    return audio.info.length
            except:
                pass
        return 0
    
    def _start_fade_in(self):
        """启动滑入效果"""
        self._stop_fade = False
        target_volume = self.volume
        
        def fade_in():
            try:
                self._fade_volume(0, target_volume, self.fade_in_duration)
            except Exception as e:
                print(f"滑入失败: {e}")
                # 失败时直接设置目标音量
                pygame.mixer.music.set_volume(target_volume / 100)
        
        self._fade_thread = threading.Thread(target=fade_in, daemon=True)
        self._fade_thread.start()
    
    def pause(self):
        """暂停播放（带滑出效果）"""
        if self.is_playing and not self.is_paused:
            self._fade_out_and_pause()
    
    def _fade_out_and_pause(self):
        """滑出后暂停"""
        self._stop_fade = False
        stop_event = threading.Event()
        current_vol = self.volume
        
        def fade_out():
            try:
                self._fade_volume(current_vol, 0, self.fade_out_duration, stop_event)
                
                if not stop_event.is_set():
                    pygame.mixer.music.pause()
                    self.is_paused = True
                    self.is_playing = False
                    # 恢复音量设置（下次播放时会重新滑入）
                    pygame.mixer.music.set_volume(self.volume / 100)
            except Exception as e:
                print(f"滑出暂停失败: {e}")
                pygame.mixer.music.pause()
                self.is_paused = True
                self.is_playing = False
        
        self._fade_thread = threading.Thread(target=fade_out, daemon=True)
        self._fade_thread.start()
        
        # 保存stop_event以便取消
        self._current_stop_event = stop_event
    
    def resume(self):
        """恢复播放（带滑入效果）"""
        self._stop_fade = True
        if hasattr(self, '_current_stop_event'):
            self._current_stop_event.set()
        
        if self.is_paused:
            try:
                pygame.mixer.music.set_volume(0)
                pygame.mixer.music.unpause()
                self.is_paused = False
                self.is_playing = True
                
                # 启动滑入
                self._start_fade_in()
            except:
                pass
    
    def stop(self):
        """停止播放（带/不带滑出效果）"""
        # if self.is_playing or self.is_paused:
        #     self._fade_out_and_stop()
        # else:
        #     self._hard_stop()
        self._hard_stop()

    def _fade_out_and_stop(self):
        """滑出后停止"""
        self._stop_fade = False
        stop_event = threading.Event()
        current_vol = self.volume if self.is_playing else 0
        
        def fade_out():
            try:
                if self.is_playing:
                    self._fade_volume(current_vol, 0, self.fade_out_duration, stop_event)
                
                if not stop_event.is_set():
                    self._hard_stop()
            except Exception as e:
                print(f"滑出停止失败: {e}")
                self._hard_stop()
        
        self._fade_thread = threading.Thread(target=fade_out, daemon=True)
        self._fade_thread.start()
        
        # 保存stop_event以便取消
        self._current_stop_event = stop_event
    
    def _hard_stop(self):
        """硬停止（无滑音）"""
        self._stop_fade = True
        if hasattr(self, '_current_stop_event'):
            self._current_stop_event.set()
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        except:
            pass
        self.is_playing = False
        self.is_paused = False
        self.current_position = 0
        self._audio_data = None
        self._audio_pos = 0
    
    def cancel_auto_next(self):
        """取消自动下一首定时器"""
        if self._auto_next_timer:
            self._auto_next_timer.cancel()
            self._auto_next_timer = None
    
    def schedule_auto_next(self, delay, callback):
        """安排自动下一首"""
        self.cancel_auto_next()
        self._auto_next_timer = threading.Timer(delay, callback)
        self._auto_next_timer.daemon = True
        self._auto_next_timer.start()
    
    def set_volume(self, volume):
        """设置音量"""
        self.volume = max(0, min(100, volume))
        if self.is_playing and not self.is_paused:
            pygame.mixer.music.set_volume(self.volume / 100)
    
    def get_position(self):
        """获取当前播放位置"""
        if self.is_playing or self.is_paused:
            try:
                pos = pygame.mixer.music.get_pos()
                if pos >= 0:
                    return pos / 1000.0
            except:
                pass
        return 0
    
    def get_length(self):
        """获取音乐长度"""
        return self.current_length
    
    def clean_temp_files(self):
        """清理临时文件"""
        try:
            if os.path.exists(self._temp_dir):
                import shutil
                shutil.rmtree(self._temp_dir)
                print("临时文件已清理")
        except Exception as e:
            print(f"清理临时文件失败: {e}")


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
        
        # 加载歌曲配置
        self.load_song_configs()
        
        # 定时器管理
        self.timer_threads = []
        
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
        self._is_transitioning = False       # 防止重复过渡
        self._auto_next_scheduled = False    # 防止重复调度

        # 拖动排序相关变量
        self._drag_start_index = None  # 拖动开始的索引
        self._drag_target_index = None  # 拖动目标的索引
        self._drag_indicator = None  # 拖动指示线
        self._drag_canvas = None  # 拖动指示线的Canvas
        self._dragged_item = None  # 拖动的行

        self.setup_shortcuts()
        self.setup_drag_drop()
        
        # 绑定窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # 启动进度更新线程
        self.update_progress_thread()
        
        # 启动VU表更新线程
        self.update_vu_meter_thread()
    
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
        
        # 播放模式子菜单
        self.play_mode_submenu = tk.Menu(play_menu, tearoff=0)
        self.play_mode_submenu.add_command(label="▶ 顺序播放", command=lambda: self.set_play_mode("sequential"))
        self.play_mode_submenu.add_command(label="  单曲循环", command=lambda: self.set_play_mode("single_loop"))
        self.play_mode_submenu.add_command(label="  随机播放", command=lambda: self.set_play_mode("random"))
        play_menu.add_cascade(label="播放模式 ▸", menu=self.play_mode_submenu)
        
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
        self.bind_hover(self.stop_btn, "停止：不带滑出的硬停止，点击停止按钮可重头播放舞曲")
        
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
                    #    tickinterval=20,    # 每隔20显示一个刻度数字 (0, 20, 40...)
                    #    resolution=1,       # 拖动一次改变1个数值
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

        # 👇 新增：为均衡器绑定右键菜单
        eq_frame.bind('<Button-3>', self.show_eq_context_menu)
        self.bind_hover(eq_frame, "七段均衡器：均衡效果仅对当前舞曲有效，并自动保存到舞曲中，右键可重置")
                
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
        # 👇 新增：为音频调节绑定右键菜单
        tempo_frame.bind('<Button-3>', self.show_tempo_context_menu)
        self.bind_hover(tempo_frame, "音频调节：变速不变调，变调不变速，仅对当前舞曲有效，并自动保存到舞曲中，右键可重置")

        # 节拍滑块
        tk.Label(tempo_frame, text="节拍", bg='white').pack(anchor='c', pady=(0, 0))
        self.beat_slider = ttk.Scale(tempo_frame, from_=30, to=150,
                                    orient=tk.HORIZONTAL,
                                    command=self.on_beat_change)
        self.beat_slider.set(90)
        self.beat_slider.pack(pady=(0, 5), fill=tk.X, padx=5)
        self.bind_hover(self.beat_slider, "节拍调节")

        # 速度滑块
        tk.Label(tempo_frame, text="速度", bg='white').pack(anchor='c', pady=(0, 0))
        self.speed_slider = ttk.Scale(tempo_frame, from_=50, to=150,
                                    orient=tk.HORIZONTAL,
                                    command=self.on_speed_change)
        self.speed_slider.set(100)
        self.speed_slider.pack(pady=(0, 5), fill=tk.X, padx=5)
        self.bind_hover(self.speed_slider, "速度调节")

        # 音调滑块
        tk.Label(tempo_frame, text="音调", bg='white').pack(anchor='c', pady=(0, 0))
        self.pitch_slider = ttk.Scale(tempo_frame, from_=-12, to=12,
                                    orient=tk.HORIZONTAL,
                                    command=self.on_pitch_change)
        self.pitch_slider.set(0)
        self.pitch_slider.pack(pady=(0, 5), fill=tk.X, padx=5)
        self.bind_hover(self.pitch_slider, "音调调节")

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
                        # 获取真实的音频电平数据
                        left_level, right_level = self.player.get_audio_levels()
                        
                        # 根据音量调整电平
                        volume_factor = self.player.volume / 100.0
                        left_level *= volume_factor
                        right_level *= volume_factor
                        
                        # 在主线程中更新VU表
                        self.root.after(0, self.update_vu_meters, left_level, right_level)
                    else:
                        # 不播放时VU表归零
                        self.root.after(0, self.update_vu_meters, 0.0, 0.0)
                except Exception as e:
                    print(f"VU表更新错误: {e}")
                
                time.sleep(0.05)  # 每0.05秒更新一次，提高响应速度
        
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
            self.bind_hover(btn, f"播放列表: {playlist_data['name']}，右键菜单进行管理")

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
            
            # 更新滑块位置（不触发事件）
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
        
        # 重置当前选中歌曲的速度音调配置
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
        """速度改变事件 - 应用于当前选中歌曲"""
        if self._updating_sliders:
            return
            
        speed = round(float(value))
        song_path = self.get_selected_song_path()
        
        if song_path:
            if song_path not in self.song_configs:
                self.song_configs[song_path] = {}
            self.song_configs[song_path]['speed'] = speed
            self.save_song_configs()
            self.status_label.config(text=f"速度: {round(float(value))/100:.1f}")
            
            # 更新表格
            self.update_song_table_row(song_path, 'speed', speed)
            
            # 如果正在播放这首歌，重新播放
            if self.player.current_file == song_path and self.player.is_playing:
                current_pos = self.player.get_position()
                self.play_song_by_index(self.player.current_index, start_pos=current_pos)
        else:
            self.status_label.config(text="请先选择一首歌曲")
    
    def on_pitch_change(self, value):
        """音调改变事件 - 应用于当前选中歌曲"""
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
            
            # 更新表格
            self.update_song_table_row(song_path, 'pitch', pitch)
            
            # 如果正在播放这首歌，重新播放
            if self.player.current_file == song_path and self.player.is_playing:
                current_pos = self.player.get_position()
                self.play_song_by_index(self.player.current_index, start_pos=current_pos)
        else:
            self.status_label.config(text="请先选择一首歌曲")
    
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
    
    def play_song_by_index(self, song_index, start_pos=None):
        """根据索引播放歌曲（应用配置）"""
        songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
        if song_index < 0 or song_index >= len(songs):
            print(f"无效的歌曲索引: {song_index}")
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
        
        # 获取歌曲配置参数, 如果没有配置播放时长，使用歌曲总时长减去起始时间
        if start_pos is not None:
            actual_start_pos = start_pos
        else:
            actual_start_pos = config.get('start_time', self.default_settings['start_time'])
        
        # 获取歌曲总时长
        total_duration = self.get_audio_duration_seconds(file_path)
        
        # 计算实际播放时长
        if 'play_duration' in config and config['play_duration'] > 0:
            # 用户设置了播放时长，使用设置值
            play_duration = config['play_duration']
        else:
            # 没有设置或设置无效，使用歌曲剩余时长（总时长-起始时间）
            play_duration = max(0, total_duration - actual_start_pos)
        
        pause_duration = config.get('pause_duration', self.default_settings['pause_duration'])
        volume = config.get('volume', self.default_settings['volume'])
        speed = config.get('speed', self.default_settings['speed'])
        pitch = config.get('pitch', self.default_settings['pitch'])
        fade_in_duration = config.get('fade_in_duration', self.default_settings['fade_in_duration'])
        fade_out_duration = config.get('fade_out_duration', self.default_settings['fade_out_duration'])
        
        # 速度转换为倍率
        speed_ratio = speed / 100.0
        
        self._auto_next_scheduled = False

        # 设置播放器参数
        self.player.set_volume(volume)
        self.player.fade_in_duration = fade_in_duration
        self.player.fade_out_duration = fade_out_duration
        
        # 更新滑块（不触发事件）
        self._updating_sliders = True
        self.volume_scale.set(volume)
        self.speed_slider.set(speed)
        self.pitch_slider.set(pitch)
        self._updating_sliders = False
        
    #    print(f"播放: {os.path.basename(file_path)}, 起始: {actual_start_pos}秒, "
    #           f"播放时长: {play_duration}秒, 停顿: {pause_duration}秒, "
    #           f"速度: {speed}%, 音调: {pitch}")
        
        # 播放（带变速变调）
        if self.player.play(file_path, start_pos=actual_start_pos, 
                           speed=speed_ratio, pitch=pitch):
            self.player.current_index = song_index
            self.status_label.config(text=f"正在播放: {os.path.basename(file_path)}")
            self.update_status_position()
            self.update_play_times()
            self.show_metadata(file_path)
            self.highlight_playing_song()
            
            # 设置进度条总时长（使用播放时长而不是歌曲时长）
            self.player.current_length = play_duration
            
            # 安排自动播放下一首
            total_wait_time = play_duration + pause_duration + fade_out_duration
            self.schedule_auto_next(total_wait_time)
    
    def schedule_auto_next(self, delay):
        """安排自动播放下一首"""
        if self._auto_next_scheduled:
            return
        
        self._auto_next_scheduled = True
        
        def auto_next():
            print(f"自动播放下一首，延迟: {delay}秒")
            self._auto_next_scheduled = False
            if self.player.is_playing:
                self.root.after(0, self.next_song)
        
        timer = threading.Timer(delay, auto_next)
        timer.daemon = True
        timer.start()
        self.timer_threads.append(timer)

    def play_music(self):
        """播放音乐"""
        selection = self.song_table.selection()
        if selection:
            item = selection[0]
            values = self.song_table.item(item, 'values')
            song_index = int(values[0]) - 1
            
            if self._is_transitioning:
                return
            
            # 如果当前有音乐在播放，先带滑音停止
            if self.player.is_playing or self.player.is_paused:
                self._transition_to_song(song_index)
            else:
                self.play_song_by_index(song_index)
    
    def _transition_to_song(self, song_index):
        if self._is_transitioning:
            return
        
        self._is_transitioning = True

        """平滑过渡到指定歌曲"""
        def do_transition():
            try:
                # 停止当前播放（带滑出）
                self.player.stop()
                # 等待滑出完成
                time.sleep(self.player.fade_out_duration)
                # 播放新歌曲（带滑入）
                self.root.after(0, lambda: self._finish_transition(song_index))
            except Exception as e:
                print(f"过渡失败: {e}")
                self._is_transitioning = False
        
        threading.Thread(target=do_transition, daemon=True).start()
    
    def _finish_transition(self, song_index):
        self.play_song_by_index(song_index)
        self._is_transitioning = False

    def pause_music(self):
        """暂停音乐（带滑音）"""
        if self.player.is_playing:
            self.player.pause()  # 带滑音暂停,假设player.pause()内部已经处理了滑音
            self.status_label.config(text="暂停")
        elif self.player.is_paused:
            self.player.resume()
            self.status_label.config(text="继续播放")
    
    def stop_music(self):
        """停止音乐（带滑音）"""
        self._auto_next_scheduled = False
        self.player.cancel_auto_next()
        
        if self.player.is_playing or self.player.is_paused:
            self.player.stop()  # 带滑音停止,假设player.stop()内部已经处理了滑音，未处理就不带
        # self.player.stop(immediate=True)    # 没有immediate 参数，可能需要重新初始化播放器或调用底层 API
        self.status_label.config(text="停止播放")
        self.progress_bar['value'] = 0
        self.current_time_label.config(text="00:00")
        self.percent_label.config(text="0%")
        self.status_position_label.config(text="0/0")
        self.status_time_display_label.config(text="00:00 / 00:00")
        
    def previous_song(self):
        """上一首"""
        if self._is_transitioning:
            return
            
        songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
        if not songs:
            return
        
        self.player.playlist = songs
        if self.player.current_index < 0:
            self.player.current_index = 0
        
        self.player.current_index = (self.player.current_index - 1) % len(songs)
        
        # 使用统一的过渡方法
        if self.player.is_playing or self.player.is_paused:
            self._transition_to_song(self.player.current_index)
        else:
            self.play_song_by_index(self.player.current_index)

    def next_song(self):
        """下一首（自动播放）"""
        if self._is_transitioning:
            return
            
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

        # 使用统一的过渡方法
        if self.player.is_playing or self.player.is_paused:
            self._transition_to_song(self.player.current_index)
        else:
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
        if self._updating_sliders:
            return
            
        volume = int(float(value))
        self.player.set_volume(volume)
        
        # 保存到当前选中歌曲的配置
        song_path = self.get_selected_song_path()
        if song_path:
            if song_path not in self.song_configs:
                self.song_configs[song_path] = {}
            self.song_configs[song_path]['volume'] = volume
            self.save_song_configs()

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
        
        for item in self.song_table.get_children():
            self.song_table.delete(item)

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
            
            # 计算显示用的播放时长
            if 'play_duration' in config and config['play_duration'] > 0:
                # 用户设置了播放时长，显示设置值
                play_duration = config['play_duration']
            else:
                # 没有设置，显示歌曲剩余时长
                play_duration = max(0, duration_seconds - start_time)
            
            pause_duration = config.get('pause_duration', self.default_settings['pause_duration'])
            volume = config.get('volume', self.default_settings['volume'])
            speed = config.get('speed', self.default_settings['speed'])
            pitch = config.get('pitch', self.default_settings['pitch'])
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
                str(speed),
                str(pitch),
                light
            )
            self.song_table.insert('', 'end', values=row)
    
    def calculate_play_time(self, index, songs):
        """计算预计播放时间（使用播放时长和停顿时长）"""
        now = datetime.datetime.now()
        total_seconds = 0
        
        current_index = self.player.current_index if self.player.current_index >= 0 else -1
        
        if current_index >= 0 and current_index < index - 1:
            for i in range(current_index, index - 1):
                if i < len(songs):
                    duration = self.get_audio_duration_seconds(songs[i])
                    config = self.song_configs.get(songs[i], {})
                    start_time = config.get('start_time', self.default_settings['start_time'])
                    
                    # 计算实际播放时长
                    if 'play_duration' in config and config['play_duration'] > 0:
                        play_duration = config['play_duration']
                    else:
                        play_duration = max(0, duration - start_time)
                    
                    pause_duration = config.get('pause_duration', self.default_settings['pause_duration'])
                    total_seconds += play_duration + pause_duration
            
            play_time = now + datetime.timedelta(seconds=total_seconds)
            return play_time.strftime("%H:%M")
        elif current_index == index - 1:
            return now.strftime("%H:%M")
        else:
            return ""
    
    def get_play_duration(self, file_path, config):
        """获取播放时长（统一处理逻辑）"""
        total_duration = self.get_audio_duration_seconds(file_path)
        start_time = config.get('start_time', self.default_settings['start_time'])
        
        # 如果用户设置了播放时长且大于0，使用设置值
        if 'play_duration' in config and config['play_duration'] > 0:
            return config['play_duration']
        
        # 否则使用歌曲剩余时长（总时长-起始时间），确保不为负数
        return max(0, total_duration - start_time)
    
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
                audio = mutagen.File(file_path)
                if audio and hasattr(audio, 'info'):
                    duration = audio.info.length
                    if hasattr(self.player, '_length_cache'):
                        self.player._length_cache[file_path] = duration
                    return duration
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
                # 显示搜索结果
                self.song_table.delete(*self.song_table.get_children())
                for i, (playlist_id, song) in enumerate(results, 1):
                    song_name = os.path.basename(song)
                    duration_seconds = self.get_audio_duration_seconds(song)
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

        # 保存按钮
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
        song_duration = self.get_audio_duration_seconds(song_path)
        
        dialog = tk.Toplevel(self.root)
        dialog.title(f"编辑歌曲: {os.path.basename(song_path)}")
        dialog.geometry("250x250+635+365")
        dialog.transient(self.root)
        dialog.grab_set()

        # 主容器
        main_frame = tk.Frame(dialog)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 左侧编辑区域
        edit_frame = tk.Frame(main_frame)
        edit_frame.grid(row=0, column=0, sticky='nsew')

        # 右侧按钮区域
        button_frame = tk.Frame(main_frame)
        button_frame.grid(row=0, column=1, sticky='ns', padx=(15, 0))

        # 配置权重
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_columnconfigure(1, weight=0)

        # 输入控件
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
            """保存当前配置，返回是否成功"""
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
            """切换歌曲，direction为-1表示上一首，1表示下一首"""
            # 先保存当前配置
            if not save_current_config():
                return  # 保存失败则不切换
            
            new_index = song_index + direction
            
            if 0 <= new_index < len(songs):
                # 有效的索引，切换
                self.song_table.selection_set(self.song_table.get_children()[new_index])
                dialog.destroy()
                self.show_song_edit_dialog()
            else:
                # 超出范围
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

        # 按钮垂直排列(函数必须在使用前定义,不能放在label后)
        tk.Button(button_frame, text="上一曲", command=prev_song, 
                bg='#3498db', fg='white', width=8).pack(pady=15)
        tk.Button(button_frame, text="重置", command=self.reset_song_config,
                bg="#d03434", fg='white', width=8).pack(pady=15)
        tk.Button(button_frame, text="下一曲", command=next_song,
                bg='#3498db', fg='white', width=8).pack(pady=15)
    
    def on_table_double_click(self, event):
        """表格双击事件 - 双击任意位置从头播放"""
        item = self.song_table.identify_row(event.y)
        if item:
            self.song_table.selection_set(item)
            values = self.song_table.item(item, 'values')
            song_index = int(values[0]) - 1
            # 从头播放
            self.play_song_by_index(song_index)

    def on_table_drag_start(self, event):
        """表格拖动开始"""
        # 获取点击的行
        item = self.song_table.identify_row(event.y)
        if item:
            self._drag_start_index = self.song_table.index(item)
            self._drag_target_index = self._drag_start_index
            # 记录拖动的行
            self._dragged_item = item

    def on_table_drag_motion(self, event):
        """表格拖动过程中"""
        if self._drag_start_index is None:
            return
        
        # 获取当前鼠标所在的行
        target_item = self.song_table.identify_row(event.y)
        if target_item:
            target_index = self.song_table.index(target_item)
            
            # 如果目标位置改变，更新指示线
            if target_index != self._drag_target_index:
                self._drag_target_index = target_index
                self.show_drag_indicator(target_index, event.y)

    def on_table_drag_end(self, event):
        """表格拖动结束"""
        if self._drag_start_index is None:
            return
        
        # 获取释放位置的行
        target_item = self.song_table.identify_row(event.y)
        if target_item:
            target_index = self.song_table.index(target_item)
            
            # 如果位置有变化，执行移动
            if target_index != self._drag_start_index:
                self.move_song_in_playlist(self._drag_start_index, target_index)
        
        # 清除拖动指示线
        self.clear_drag_indicator()
        
        # 重置拖动变量
        self._drag_start_index = None
        self._drag_target_index = None
        self._dragged_item = None

    def show_drag_indicator(self, target_index, y_pos):
        """显示拖动指示（使用行高亮）"""
        self.clear_drag_indicator()
        
        # 获取目标行的位置
        items = self.song_table.get_children()
        if target_index < len(items):
            target_item = items[target_index]
            bbox = self.song_table.bbox(target_item)
            if bbox:
                x, y, width, height = bbox
                
                # 判断是在目标行的上方还是下方
                if y_pos < y + height / 2:
                    # 在上方时，高亮当前行
                    self.song_table.item(target_item, tags=('drag_target',))
                    if target_index > 0:
                        # 同时清除上一行的高亮
                        prev_item = items[target_index - 1]
                        self.song_table.item(prev_item, tags=())
                else:
                    # 在下方时，高亮当前行
                    self.song_table.item(target_item, tags=('drag_target',))
                    if target_index < len(items) - 1:
                        # 同时清除下一行的高亮
                        next_item = items[target_index + 1]
                        self.song_table.item(next_item, tags=())
                
                # 配置drag_target标签的样式
                self.song_table.tag_configure('drag_target', background='#ffcccc')

    def clear_drag_indicator(self):
        """清除拖动指示"""
        # 清除所有行的drag_target标签
        items = self.song_table.get_children()
        for item in items:
            self.song_table.item(item, tags=())
        self._drag_indicator = None

    def move_song_in_playlist(self, from_index, to_index):
        """在播放列表中移动歌曲"""
        songs = self.playlist_manager.playlists[self.current_playlist]["songs"]
        
        if 0 <= from_index < len(songs) and 0 <= to_index < len(songs):
            # 使用PlaylistManager的move_song方法
            if self.playlist_manager.move_song(self.current_playlist, from_index, to_index):
                # 重新加载播放列表
                self.load_playlist(self.current_playlist)
                self.status_label.config(text="歌曲顺序已调整")
                
                # 如果移动的是当前播放的歌曲，更新当前索引
                if self.player.current_index == from_index:
                    self.player.current_index = to_index
                elif from_index < self.player.current_index <= to_index:
                    self.player.current_index -= 1
                elif to_index <= self.player.current_index < from_index:
                    self.player.current_index += 1

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