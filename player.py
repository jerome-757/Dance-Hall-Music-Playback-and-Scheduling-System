# player.py

import os
import tempfile
import hashlib
import threading
import time
import pygame
import librosa

import mutagen
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.wave import WAVE
from mutagen.oggvorbis import OggVorbis
from mutagen.mp4 import MP4

import numpy as np
import soundfile as sf
import warnings
warnings.filterwarnings("ignore", message=".*avx2 capable.*")

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
        self._play_lock = threading.Lock()
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

    def prepare_audio(self, file_path, speed=1.0, pitch=0):
        """预处理音频，返回（处理后的文件路径，是否临时文件，实际时长）"""
        return self._apply_audio_effects_with_duration(file_path, speed, pitch)

    def _apply_audio_effects_with_duration(self, file_path, speed=1.0, pitch=0):
        """应用音频效果，返回（文件路径，是否临时，实际时长）"""
        try:
            # 如果速度和音调都是默认值，直接返回原文件
            if abs(speed - 1.0) < 0.01 and abs(pitch) < 0.01:
                return file_path, False, self._get_file_length(file_path)
            
            # 生成临时文件路径
            temp_file = self._get_temp_file_path(file_path, speed, pitch)
            
            # 如果临时文件已存在，直接使用
            if os.path.exists(temp_file):
                print(f"📁 使用缓存的临时文件: {os.path.basename(temp_file)}")
                return temp_file, True, self._get_file_length(temp_file)
            
            # print(f"⚙️ 处理音频: {os.path.basename(file_path)}, 速度={speed:.2f}x, 音调={pitch}半音")
            
            # 加载音频
            y, sr = librosa.load(file_path, sr=None)
            original_duration = len(y) / sr
            print(f"   ├─ 原始时长: {original_duration:.2f}s")
            
            # 应用速度变化
            if abs(speed - 1.0) > 0.01:
                y = librosa.effects.time_stretch(y, rate=speed)
                print(f"   ├─ 速度变换: {speed:.2f}x")
            
            # 应用音调变化
            if abs(pitch) > 0.01:
                y = librosa.effects.pitch_shift(y, sr=sr, n_steps=pitch)
                print(f"   ├─ 音调变换: {pitch}半音")

            # ✅ 修复：确保数据格式正确
            # 如果 y 是单声道，保持为 1D 数组；如果是立体声，保持为 2D
            if y.ndim == 1:
                # 单声道
                channels = 1
            else:
                channels = y.shape[0] if y.shape[0] < y.shape[1] else 1
                if channels > 1:
                    # 如果是立体声，确保形状是 (channels, samples)
                    if y.shape[0] > y.shape[1]:
                        y = y.T
            
            # ✅ 确保临时目录存在且可写
            temp_dir = os.path.dirname(temp_file)
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)
            
            # ✅ 使用锁保护临时文件操作
            with self._play_lock:
                # ✅ 检查文件是否被占用，如果存在先删除
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except:
                        pass
            
            # ✅ 使用更兼容的格式写入
            # 使用 'PCM_16' 格式，兼容性最好
            sf.write(temp_file, y, sr, subtype='PCM_16')
            
            # 计算实际时长
            actual_duration = len(y) / sr
            print(f"   └─ 处理后时长: {actual_duration:.2f}s")
            
            return temp_file, True, actual_duration
            
        except Exception as e:
            print(f"❌ 音频处理失败: {e}")
            import traceback
            traceback.print_exc()
            # ✅ 处理失败时返回原文件和原始时长
            return file_path, False, self._get_file_length(file_path)

    def load(self, file_path):
        """加载音乐文件"""
        try:
            with self._play_lock:
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
        # ✅ 修复：使用锁保护滑音操作
        with self._fade_lock:
            # ✅ 如果时长为0或很小，直接跳转
            if duration <= 1:
                pygame.mixer.music.set_volume(max(0, min(100, to_vol)) / 100)
                return
                
            steps = int(duration * 10)
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
            # 停止当前播放
            self._hard_stop()
            time.sleep(0.05)
            
            if file_path:
                self.current_file = file_path
                # 应用音频效果
                processed_file, is_temp = self._apply_audio_effects_with_duration(file_path, speed, pitch)
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
            with self._play_lock:
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
                    with self._play_lock:
                        pygame.mixer.music.pause()
                    self.is_paused = True
                    self.is_playing = False
                    # 恢复音量设置（下次播放时会重新滑入）
                    pygame.mixer.music.set_volume(self.volume / 100)
            except Exception as e:
                print(f"滑出暂停失败: {e}")
                with self._play_lock:
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
                with self._play_lock:
                    pygame.mixer.music.unpause()
                self.is_paused = False
                self.is_playing = True
                
                # 启动滑入
                self._start_fade_in()
            except:
                pass
    
    def stop(self):
        """停止播放（带/不带滑出效果）"""
        if self.is_playing or self.is_paused:
            self._fade_out_and_stop()
        else:
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
            with self._play_lock:
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()
        except:
            pass
        self.is_playing = False
        self.is_paused = False
        self.current_position = 0
        self._audio_data = None
        self._audio_pos = 0

                        
    def set_volume(self, volume):
        """设置音量"""
        self.volume = max(0, min(100, volume))
        if self.is_playing and not self.is_paused:
            pygame.mixer.music.set_volume(self.volume / 100)
    
    def get_position(self):
        """获取当前播放位置（相对于播放开始的位置）"""
        if self.is_playing or self.is_paused:
            try:
                pos = pygame.mixer.music.get_pos()
                if pos >= 0:
                    # ✅ 返回相对于播放开始的位置
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
            with self._play_lock:
                if os.path.exists(self._temp_dir):
                    import shutil
                    shutil.rmtree(self._temp_dir)
                    print("临时文件已清理")
        except Exception as e:
            print(f"清理临时文件失败: {e}")
