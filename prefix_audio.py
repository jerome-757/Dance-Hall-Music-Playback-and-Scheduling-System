#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
🎵 舞曲前缀音处理模块
功能：
  1. 自动识别舞种
  2. 多种TTS引擎（Edge/Google/本地）
  3. 语音缓存
  4. 预生成模式
  5. 与BGM混合
"""

import asyncio
import os
import subprocess
import re
import time
import hashlib
import shutil
import json
import uuid
import logging
from datetime import datetime
from typing import Optional, Dict, Tuple
import threading
from concurrent.futures import ThreadPoolExecutor

# ============================================================
# 🔧 配置参数 - 可配置选项
# ============================================================

# 默认配置
DEFAULT_CONFIG = {
    'bgm_volume': 0.2,           # 背景音乐音量（0.1 ~ 1.0）
    'bgm_start_time': 0,         # 新增：背景音乐起始时间（秒）
    'bgm_duration': 8,           # 背景音乐总时长（秒）
    'fade_in_duration': 2,     # 原曲淡入时长（秒）
    'fade_out_duration': 1,    # 前奏淡出时长（秒）
    'speech_text': '下面请欣赏',  # 语音文本前缀
    'speech_position': 'middle', # 语音位置: "start", "middle", "end"
    'tts_engine': 'edge',        # TTS引擎: 'edge', 'gtts', 'local'
    'tts_voice': 'zh-CN-YunjianNeural',  # 语音音色
}

# 当前配置（运行时可变）
BGM_VOLUME = DEFAULT_CONFIG['bgm_volume']
BGM_START_TIME = DEFAULT_CONFIG['bgm_start_time']
BGM_TOTAL_DURATION = DEFAULT_CONFIG['bgm_duration']
FADE_IN_DUR = DEFAULT_CONFIG['fade_in_duration']
FADE_OUT_DUR = DEFAULT_CONFIG['fade_out_duration']
SPEECH_TEXT = DEFAULT_CONFIG['speech_text']  
SPEECH_POSITION = DEFAULT_CONFIG['speech_position']
TTS_ENGINE = DEFAULT_CONFIG['tts_engine']
TTS_VOICE = DEFAULT_CONFIG['tts_voice']

# 支持的TTS音色列表（Edge引擎）
EDGE_VOICES = [
    'zh-CN-XiaoxiaoNeural',      # 晓晓 - 女声
    'zh-CN-XiaoyiNeural',        # 晓伊 - 女声
    'zh-CN-YunjianNeural',       # 云健 - 男声
    'zh-CN-YunxiNeural',         # 云希 - 男声
    'zh-CN-YunyangNeural',       # 云扬 - 男声
    'zh-CN-XiaohanNeural',       # 晓涵 - 女声
    'zh-CN-XiaomengNeural',      # 晓萌 - 女声
    'zh-CN-XiaorouNeural',       # 晓柔 - 女声
    'zh-CN-XiaoshuangNeural',    # 晓双 - 女声
    'zh-CN-XiaoxuanNeural',      # 晓萱 - 女声
]

# 语音位置选项
POSITION_OPTIONS = ['start', 'middle', 'end']

# TTS引擎选项
ENGINE_OPTIONS = ['edge', 'gtts', 'local']

# BGM文件名
BGM_NAMES = ["bgm.mp3", "bgm.MP3", "背景音乐.mp3", "background.mp3"]

# 缓存配置
CACHE_FOLDER = "prefix_cache"
CACHE_INDEX_FILE = "cache_index.json"
MAX_CACHE_SIZE = 500  # 最大缓存数量

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('prefix_audio.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# ============================================================
# 🎵 舞种定义 - 统一数据源
# ============================================================
# 格式: (匹配关键词列表, 舞种显示名称, 生成语音词语)
DANCE_DEFINITIONS = [
    # ========== 国标舞 ==========
    (["华尔兹", "Waltz", "W"], "华尔兹", "华尔兹舞曲"),
    (["维也纳华尔兹", "Viennese Waltz", "V"], "维也纳华尔兹", "维也纳华尔兹舞曲"),
    (["探戈", "Tango", "T"], "探戈", "探戈舞曲"),
    (["狐步", "Foxtrot", "F"], "狐步", "狐步舞曲"),
    (["快步", "Quickstep", "Q"], "快步", "快步舞曲"),
    (["伦巴", "Rumba", "R"], "伦巴", "伦巴舞曲"),
    (["恰恰", "Cha Cha", "C"], "恰恰", "恰恰舞曲"),
    (["桑巴", "Samba", "S"], "桑巴", "桑巴舞曲"),
    (["牛仔", "Jive", "J"], "牛仔", "牛仔舞曲"),
    (["斗牛", "Paso Doble", "P"], "斗牛", "斗牛舞曲"),
    
    # ========== 地方舞 ==========
    (["三步踩"], "三步踩", "武汉三步踩"),
    (["平四"], "平四", "北京平四"),
    
    # ========== 交谊舞 ==========
    (["慢三"], "慢三", "慢三"),
    (["慢四"], "慢四", "慢四"),
    (["中三"], "中三", "中三"),
    (["中四"], "中四", "中四"),
    (["快三"], "快三", "快三"),
    (["快四"], "快四", "快四"),
    (["并四"], "并四", "并四"),
    (["吉特巴"], "吉特巴", "吉特巴"),
    (["水兵舞"], "水兵舞", "水兵舞"),
    (["鬼步舞"], "鬼步舞", "鬼步舞"),
    (["点帕斯"], "点帕斯", "点帕斯"),
    (["休闲伦巴"], "休闲伦巴", "休闲伦巴"),
    
    # ========== 集体舞 ==========
    (["兔子舞"], "兔子舞", "兔子舞"),
    (["十六步"], "十六步", "十六步"),
    (["三十二步"], "三十二步", "三十二步"),
    
    # ========== 网红舞 ==========
    (["汉舞"], "汉舞", "汉舞王伦巴"),
    (["唐舞"], "唐舞", "唐舞伦巴"),
    (["周舞"], "周舞", "周舞伦巴"),
    
    # ========== 其他 ==========
    (["DJ"], "DJ", "DJ混音舞曲"),
    (["慢摇"], "慢摇", "慢摇"),
    (["民族舞"], "民族舞", "民族舞"),
    (["古典舞"], "古典舞", "古典舞"),
    (["现代舞", "Modern Dance"], "现代舞", "现代舞"),
    (["肚皮舞", "Belly Dance"], "肚皮舞", "肚皮舞"),
    (["街舞", "Hip Hop"], "街舞", "街舞"),
    (["爵士", "Jazz"], "爵士", "爵士"),
    (["芭蕾", "Ballet"], "芭蕾", "芭蕾"),
    
    # ========== 拉丁 ==========
    (["曼波", "Mambo"], "曼波", "曼波"),
    (["萨尔萨", "Salsa"], "萨尔萨", "萨尔萨"),
    (["梅伦格", "Merengue"], "梅伦格", "梅伦格"),
    (["巴恰塔", "Bachata"], "巴恰塔", "巴恰塔"),
    (["波莱罗", "Bolero"], "波莱罗", "波莱罗"),
]

# ============================================================
# 🎵 自动生成各种映射表
# ============================================================

# 1. 匹配关键词列表（用于文件识别）
DANCE_PATTERNS = []
for keywords, display_name, voice_name in DANCE_DEFINITIONS:
    for keyword in keywords:
        DANCE_PATTERNS.append((keyword, display_name))

# 2. 显示名称列表（用于界面展示）
DANCE_TYPES = []
seen = set()
for _, display_name, _ in DANCE_DEFINITIONS:
    if display_name not in seen:
        seen.add(display_name)
        DANCE_TYPES.append(display_name)

# 3. 显示名称 -> 语音名称 映射（用于生成前缀音）
DANCE_VOICE_MAP = {}
for _, display_name, voice_name in DANCE_DEFINITIONS:
    DANCE_VOICE_MAP[display_name] = voice_name

# 4. 反向映射：显示名称 -> 匹配关键词（用于预览时显示用户友好的名称）
REVERSE_DANCE_MAP = {}
for keywords, display_name, _ in DANCE_DEFINITIONS:
    for keyword in keywords:
        REVERSE_DANCE_MAP[keyword] = display_name
    REVERSE_DANCE_MAP[display_name] = display_name


def extract_dance_name(filename: str) -> str:
    """
    从文件名提取舞种名称
    匹配规则（优先级从上至下）：
    1. 中文优先于英文
    2. 特殊词组优先
    3. 长词优先于短词
    4. 完整英文名称优先于单个字母
    5. 单个字母必须是大写且必须在 -X- 或 _X_ 格式中才匹配
    6. 按文件名顺序匹配，从前往后，匹配到就停止
    7. 匹配不到输出"舞曲"
    """
    name_without_ext = os.path.splitext(filename)[0]
    
    # ========== 准备匹配规则 ==========
    # 分离中文关键词和英文关键词
    chinese_patterns = []  # 中文关键词（长度>=2，且包含中文字符）
    english_patterns = []  # 英文关键词（长度>=2，纯英文）
    single_letter_patterns = []  # 单字母关键词
    
    for keyword, dance_name in DANCE_PATTERNS:
        # 判断是否包含中文字符
        if re.search(r'[\u4e00-\u9fff]', keyword):
            chinese_patterns.append((keyword, dance_name))
        elif len(keyword) >= 2:
            english_patterns.append((keyword, dance_name))
        else:
            single_letter_patterns.append((keyword, dance_name))
    
    # 中文按长度降序排序（长词优先）
    chinese_patterns.sort(key=lambda x: len(x[0]), reverse=True)
    # 英文按长度降序排序
    english_patterns.sort(key=lambda x: len(x[0]), reverse=True)
    
    # # ========== 第一轮：括号内容优先匹配 ==========
    # bracket_patterns = [
    #     r'[《【\[\(（]([^》】\]\)）]*)[》】\]\)）]',
    #     r'[-_—]([^-_—]*)[-_—]',
    # ]
    
    # for pattern in bracket_patterns:
    #     matches = re.findall(pattern, name_without_ext)
    #     for content in matches:
    #         content = re.sub(r'[《》【】\[\]\(\)（）\-_—]', '', content)
    #         if not content:
    #             continue
            
    #         # 在括号内容中先匹配中文（长词优先）
    #         for keyword, dance_name in chinese_patterns:
    #             if keyword in content:
    #                 return dance_name
            
    #         # 再匹配完整英文
    #         for keyword, dance_name in english_patterns:
    #             if keyword.lower() in content.lower():
    #                 return dance_name
            
    #         # 最后匹配单字母（必须 -X- 格式）
    #         for keyword, dance_name in single_letter_patterns:
    #             if re.search(r'[-_]' + keyword + r'[-_]', content):
    #                 return dance_name
    
    # ========== 第二轮：按文件名顺序匹配 ==========
    parts = re.split(r'[-_—\s\.\[\]\(\)（）《》【】]+', name_without_ext)
    parts = [p for p in parts if p]
    
    for part in parts:
        # 1. 先匹配中文（长词优先）
        for keyword, dance_name in chinese_patterns:
            if keyword in part:
                # 确保是独立的中文词（不是英文单词的一部分）
                return dance_name
        
        # 2. 再匹配完整英文（长度>=2）
        for keyword, dance_name in english_patterns:
            # 检查英文关键词是否完整匹配这个part（不区分大小写）
            if keyword.lower() == part.lower():
                return dance_name
            # 或者这个part包含英文关键词（但必须是独立的）
            if len(part) > len(keyword) and keyword.lower() in part.lower():
                # 检查关键词在part中是否是独立的
                if re.search(r'(?<![a-zA-Z])' + re.escape(keyword) + r'(?![a-zA-Z])', part, re.IGNORECASE):
                    return dance_name
        
        # 3. 单字母匹配（必须是大写且符合 -X- 或 _X_ 格式）
        if len(part) == 1 and part.isupper():
            # 检查这个字母在原始文件名中是否被 - 或 _ 包围
            if re.search(r'[-_]' + part + r'[-_]', name_without_ext):
                for keyword, dance_name in single_letter_patterns:
                    if part == keyword:
                        return dance_name
    
    # ========== 第三轮：在整个文件名中查找 ==========
    # 1. 中文（长词优先）
    for keyword, dance_name in chinese_patterns:
        if keyword in name_without_ext:
            return dance_name
    
    # 2. 完整英文（长度>=2，必须独立）
    for keyword, dance_name in english_patterns:
        if re.search(r'(?<![a-zA-Z])' + re.escape(keyword) + r'(?![a-zA-Z])', name_without_ext, re.IGNORECASE):
            return dance_name
    
    # 3. 单字母（必须 -X- 格式）
    for keyword, dance_name in single_letter_patterns:
        if re.search(r'[-_]' + keyword + r'[-_]', name_without_ext):
            return dance_name
    
    # ========== 默认返回 ==========
    return "舞曲"

class PrefixAudioManager:
    """前缀音管理器"""
    
    def __init__(self):
        self.config_file = "dance_name_mapping.json"
        self.dance_mapping = {}
        self.load_dance_mapping()
        self.cache_folder = CACHE_FOLDER
        self.cache_index = {}
        self.bgm_file = None
        self._lock = threading.Lock()
        self.logger = logging.getLogger(__name__)
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.MAX_CACHE_SIZE = MAX_CACHE_SIZE
        
        # 创建缓存文件夹
        os.makedirs(self.cache_folder, exist_ok=True)
        
        # 加载缓存索引
        self._load_cache_index()
        
        # 查找BGM文件
        self._find_bgm()

    def _save_voice_only(self, speech_file: str, dance_name: str) -> Optional[str]:
        """只保留语音，不混合BGM（静音模式）"""
        try:
            import time
            import random
            timestamp = int(time.time() * 1000)
            random_suffix = random.randint(1000, 9999)
            cache_key = self.get_cache_key(dance_name)
            output_file = os.path.join(self.cache_folder, f"prefix_{cache_key}_{timestamp}_{random_suffix}.mp3")
            
            # ✅ 直接复制语音文件，不做任何混合
            import shutil
            shutil.copy2(speech_file, output_file)
            
            # 如果语音时长不够 BGM_TOTAL_DURATION，用静音填充
            speech_dur = self._get_audio_duration(speech_file)
            if speech_dur < BGM_TOTAL_DURATION:
                # 用 FFmpeg 添加静音填充到指定时长
                filter_complex = (
                    f"[0:a]apad=pad_dur={BGM_TOTAL_DURATION},"

                    f"afade=t=out:st={BGM_TOTAL_DURATION-FADE_OUT_DUR}:d={FADE_OUT_DUR}"
                )
                cmd = [
                    'ffmpeg',
                    '-i', speech_file,
                    '-filter_complex', filter_complex,
                    '-c:a', 'libmp3lame',
                    '-b:a', '192k',
                    '-y',
                    output_file
                ]
                result = subprocess.run(cmd, capture_output=True, timeout=30)
                if result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                    return output_file
                # 如果失败，返回原文件
                return speech_file
            
            return output_file
            
        except Exception as e:
            self.logger.error(f"保存纯语音失败: {e}")
            return None

    def get_available_bgm_files(self):
        """获取可用的背景音乐文件列表"""
        # ✅ 默认第一个是"不选择音乐"
        bgm_files = ["不选择音乐"]
        
        # ✅ 第二个是内置BGM
        bgm_files.append("使用内置BGM")

        # 检查 BGM_DIR 是否存在
        bgm_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bgm")
        if not os.path.exists(bgm_dir):
            os.makedirs(bgm_dir, exist_ok=True)
        
        # 扫描 bgm 目录
        if os.path.exists(bgm_dir):
            for file in os.listdir(bgm_dir):
                if file.lower().endswith(('.mp3', '.wav', '.flac', '.m4a', '.ogg')):
                    bgm_files.append(file)

        return bgm_files        
        # # 如果 bgm 目录为空，检查根目录是否有 bgm 文件
        # if not bgm_files:
        #     current_dir = os.path.dirname(os.path.abspath(__file__))
        #     for f in os.listdir(current_dir):
        #         f_lower = f.lower()
        #         if 'bgm' in f_lower and f_lower.endswith(('.mp3', '.wav', '.flac')):
        #             bgm_files.append(f)
        
        # return sorted(bgm_files)

    def load_dance_mapping(self):
        """加载舞种映射配置"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.dance_mapping = json.load(f)
        except Exception as e:
            self.logger.error(f"加载舞种映射失败: {e}")
            self.dance_mapping = {}
    
    def save_dance_mapping(self):
        """保存舞种映射配置"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.dance_mapping, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"保存舞种映射失败: {e}")
    
    def get_dance_name(self, filename):
        """获取舞种名称（优先使用手动映射）"""
        # 先检查手动映射
        if filename in self.dance_mapping:
            return self.dance_mapping[filename]
        
        # 使用自动提取
        dance_name = extract_dance_name(filename)
        return dance_name
    
    def set_dance_name(self, filename, dance_name):
        """手动设置舞种名称"""
        self.dance_mapping[filename] = dance_name
        self.save_dance_mapping()
        
        # 重新生成前缀音
        self.generate_prefix(dance_name)
        
        return True

    def _load_cache_index(self):
        """加载缓存索引"""
        try:
            index_file = os.path.join(self.cache_folder, CACHE_INDEX_FILE)
            if os.path.exists(index_file):
                with open(index_file, 'r', encoding='utf-8') as f:
                    self.cache_index = json.load(f)
        except Exception as e:
            self.logger.error(f"加载缓存索引失败: {e}")
            self.cache_index = {}
    
    def _save_cache_index(self):
        """保存缓存索引"""
        try:
            index_file = os.path.join(self.cache_folder, CACHE_INDEX_FILE)
            with open(index_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache_index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"保存缓存索引失败: {e}")
    
    # def _find_bgm(self):
    #     """查找BGM文件"""
    #     current_dir = os.path.dirname(os.path.abspath(__file__))
        
    #     for name in BGM_NAMES:
    #         test_path = os.path.join(current_dir, name)
    #         if os.path.exists(test_path):
    #             self.bgm_file = test_path
    #             self.logger.info(f"找到BGM: {name}")
    #             return
        
    #     # 自动搜索包含bgm的文件
    #     for f in os.listdir(current_dir):
    #         f_lower = f.lower()
    #         if 'bgm' in f_lower and f_lower.endswith(('.mp3', '.wav', '.flac')):
    #             self.bgm_file = os.path.join(current_dir, f)
    #             # print(f"✅ 找到BGM（自动识别）: {f}")
    #             return
        
    #     self.logger.warning("未找到BGM文件，将使用静音")

    def _find_bgm(self):
        """查找BGM文件（支持 bgm/ 子目录）"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        bgm_dir = os.path.join(current_dir, "bgm")
        
        # ========== 1. 先在 bgm/ 目录中查找 ==========
        if os.path.exists(bgm_dir):
            for name in BGM_NAMES:
                test_path = os.path.join(bgm_dir, name)
                if os.path.exists(test_path):
                    self.bgm_file = test_path
                    self.logger.info(f"找到BGM（bgm目录）: {test_path}")
                    return
            
            # 在 bgm/ 目录中自动搜索包含 bgm 的文件
            for f in os.listdir(bgm_dir):
                f_lower = f.lower()
                if 'bgm' in f_lower and f_lower.endswith(('.mp3', '.wav', '.flac')):
                    self.bgm_file = os.path.join(bgm_dir, f)
                    self.logger.info(f"找到BGM（bgm目录自动识别）: {f}")
                    return
        
        # ========== 2. 再在当前根目录查找 ==========
        for name in BGM_NAMES:
            test_path = os.path.join(current_dir, name)
            if os.path.exists(test_path):
                self.bgm_file = test_path
                self.logger.info(f"找到BGM（根目录）: {name}")
                return
        
        # 在根目录自动搜索包含 bgm 的文件
        for f in os.listdir(current_dir):
            f_lower = f.lower()
            if 'bgm' in f_lower and f_lower.endswith(('.mp3', '.wav', '.flac')):
                self.bgm_file = os.path.join(current_dir, f)
                self.logger.info(f"找到BGM（根目录自动识别）: {f}")
                return
        
        self.logger.warning("未找到BGM文件，请在根目录创建bgm文件夹，否则将使用静音")

    def get_config_hash(self) -> str:
        """获取当前配置的哈希值"""
        config_str = f"{BGM_VOLUME}_{BGM_START_TIME}_{SPEECH_POSITION}_{TTS_ENGINE}_{TTS_VOICE}_{BGM_TOTAL_DURATION}_{FADE_OUT_DUR}_{SPEECH_TEXT}"
        return hashlib.md5(config_str.encode('utf-8')).hexdigest()[:8]
    
    def get_cache_key(self, dance_name: str) -> str:
        """生成缓存键（包含配置信息）"""
        config_hash = self.get_config_hash()
        config_str = f"{dance_name}_{config_hash}"
        return hashlib.md5(config_str.encode('utf-8')).hexdigest()[:16]
    
    def get_cached_prefix(self, dance_name: str) -> Optional[str]:
        """获取缓存的前缀音"""
        cache_key = self.get_cache_key(dance_name)
        
        if cache_key in self.cache_index:
            cached_file = self.cache_index[cache_key].get('file')
            if cached_file and os.path.exists(cached_file):
                return cached_file
        
        return None
    
    def _get_cached_file_by_key(self, cache_key: str) -> Optional[str]:
        """根据缓存键获取缓存文件"""
        if cache_key in self.cache_index:
            cached_file = self.cache_index[cache_key].get('file')
            if cached_file and os.path.exists(cached_file):
                return cached_file
        return None
    
    def _cleanup_old_cache(self):
        """清理旧的缓存（智能清理）"""
        try:
            sorted_items = sorted(
                self.cache_index.items(),
                key=lambda x: x[1].get('created', ''),
                reverse=True
            )
            
            if len(sorted_items) > self.MAX_CACHE_SIZE:
                to_keep = set(item[0] for item in sorted_items[:self.MAX_CACHE_SIZE])
                
                for key in list(self.cache_index.keys()):
                    if key not in to_keep:
                        file_path = self.cache_index[key].get('file')
                        if file_path and os.path.exists(file_path):
                            try:
                                os.remove(file_path)
                            except:
                                pass
                        del self.cache_index[key]
                
                self._save_cache_index()
                self.logger.info(f"清理了 {len(sorted_items) - self.MAX_CACHE_SIZE} 个旧缓存")
                
        except Exception as e:
            self.logger.error(f"清理缓存失败: {e}")
    def generate_prefix(self, dance_name: str, force_regenerate: bool = False, 
                    callback=None, bgm_file: str = None) -> Optional[str]:
        """生成前缀音（支持自定义BGM）
        
        Args:
            dance_name: 舞种名称
            force_regenerate: 是否强制重新生成
            callback: 回调函数
            bgm_file: 自定义BGM文件路径（如果为None则使用默认）
        """
        with self._lock:
            # 检查缓存（如果使用自定义BGM，不使用缓存）
            if not force_regenerate and bgm_file is None:
                cached = self.get_cached_prefix(dance_name)
                if cached:
                    self.logger.info(f"使用缓存前缀音: {dance_name}")
                    if callback:
                        callback(cached)
                    return cached
            
            try:
                # 生成语音
                speech_file = self._generate_speech(dance_name)
                if not speech_file:
                    self.logger.error(f"语音生成失败: {dance_name}")
                    return None
                
                # ========== 混合BGM和语音 ==========
                # 如果 bgm_file 是 "不选择音乐" 或 None，则静音
                if bgm_file == "不选择音乐":
                    # ✅ 不混合BGM，只保留语音
                    output_file = self._save_voice_only(speech_file, dance_name)
                else:
                    # 正常混合BGM
                    output_file = self._mix_audio(speech_file, dance_name, bgm_file=bgm_file)
                
                # 清理临时语音文件
                if os.path.exists(speech_file):
                    try:
                        os.remove(speech_file)
                    except:
                        pass
                
                if output_file and os.path.exists(output_file):
                    # 如果使用了自定义BGM，不缓存（因为配置可能会变）
                    if bgm_file is None or bgm_file == "使用内置BGM":
                        config_hash = self.get_config_hash()
                        cache_key = self.get_cache_key(dance_name)
                        
                        self.cache_index[cache_key] = {
                            'dance_name': dance_name,
                            'file': output_file,
                            'created': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            'version': '1.0',
                            'config': {
                                'duration': BGM_TOTAL_DURATION,
                                'volume': BGM_VOLUME,
                                'position': SPEECH_POSITION,
                                'engine': TTS_ENGINE,
                                'voice': TTS_VOICE,
                                'fade_out': FADE_OUT_DUR,
                                'speech_text': SPEECH_TEXT,
                                'config_hash': config_hash
                            }
                        }
                        self._save_cache_index()
                    
                    self.logger.info(f"前缀音生成成功: {dance_name}")
                    if callback:
                        callback(output_file)
                    return output_file
                
            except Exception as e:
                self.logger.error(f"前缀音生成失败: {e}")
                import traceback
                traceback.print_exc()
            
            return None
    
    def _generate_speech(self, dance_name: str) -> Optional[str]:
        """生成语音"""
        # ✅ 如果 SPEECH_TEXT 为空，只念舞种名称
        if not SPEECH_TEXT or SPEECH_TEXT.strip() == "":
            speech_text = dance_name
        else:
            speech_text = f"{SPEECH_TEXT}。{dance_name}"
        
        unique_id = uuid.uuid4().hex[:8]
        temp_speech = os.path.join(self.cache_folder, f"temp_speech_{unique_id}.mp3")
        
        # TTS引擎优先级
        engine_priority = {
            'edge': [self._generate_edge_tts, self._generate_gtts, self._generate_local_tts],
            'gtts': [self._generate_gtts, self._generate_edge_tts, self._generate_local_tts],
            'local': [self._generate_local_tts, self._generate_edge_tts, self._generate_gtts]
        }
        
        engines = engine_priority.get(TTS_ENGINE, engine_priority['edge'])
        
        for engine_func in engines:
            try:
                if engine_func(speech_text, temp_speech):
                    if os.path.exists(temp_speech) and os.path.getsize(temp_speech) > 0:
                        return temp_speech
            except Exception as e:
                self.logger.error(f"TTS引擎失败 ({engine_func.__name__}): {e}")
                continue
        
        return None
    
    def _generate_edge_tts(self, text: str, output_file: str) -> bool:
        """使用Edge TTS"""
        try:
            import edge_tts
            import asyncio
            
            # 使用配置的语音音色
            voice = TTS_VOICE if TTS_VOICE else "zh-CN-YunjianNeural"
            
            async def _generate():
                communicate = edge_tts.Communicate(text, voice)
                await communicate.save(output_file)
            
            asyncio.run(_generate())
            return True
        except ImportError:
            return False
        except Exception as e:
            self.logger.error(f"Edge TTS失败: {e}")
            return False
    
    def _generate_gtts(self, text: str, output_file: str) -> bool:
        """使用Google TTS"""
        try:
            from gtts import gTTS
            import gtts.lang
            
            # 查看支持的语言代码
            # print("支持的语言:", gtts.lang.tts_langs())
            
            # 尝试不同的语言代码
            lang_codes = ['zh-CN', 'zh', 'cmn-Hans-CN', 'zh-Hans']
            
            for lang_code in lang_codes:
                try:
                    tts = gTTS(text=text, lang=lang_code, slow=False)
                    tts.save(output_file)
                    return True
                except Exception as e:
                    self.logger.warning(f"尝试语言代码 {lang_code} 失败: {e}")
                    continue
            
            return False
        except ImportError:
            return False
        except Exception as e:
            self.logger.error(f"Google TTS失败: {e}")
            return False
    
    def _generate_local_tts(self, text: str, output_file: str) -> bool:
        """使用本地TTS"""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            
            # 设置中文语音
            voices = engine.getProperty('voices')
            for voice in voices:
                if 'zh' in voice.id.lower() or 'chinese' in voice.id.lower():
                    engine.setProperty('voice', voice.id)
                    break
            
            # 保存为wav
            temp_wav = output_file.replace('.mp3', '.wav')
            engine.save_to_file(text, temp_wav)
            engine.runAndWait()
            engine.stop()
            
            # 转换为mp3
            if os.path.exists(temp_wav):
                cmd = [
                    'ffmpeg',
                    '-i', temp_wav,
                    '-c:a', 'libmp3lame',
                    '-b:a', '192k',
                    '-y',
                    output_file
                ]
                subprocess.run(cmd, capture_output=True, check=True)
                os.remove(temp_wav)
                return True
            
            return False
        except ImportError:
            return False
        except Exception as e:
            self.logger.error(f"本地TTS失败: {e}")
            return False
    
    def _mix_audio(self, speech_file: str, dance_name: str, 
                max_retries: int = 3, bgm_file: str = None) -> Optional[str]:
        """混合BGM和语音（带重试机制，支持自定义BGM）"""
        # ========== 第一步：声明要修改的全局变量（必须放在最前面） ==========
        global BGM_START_TIME, BGM_TOTAL_DURATION
        
        # ========== 确定使用的BGM文件 ==========
        use_bgm_file = None
        
        # ✅ 如果 bgm_file 是 None，检查模块级变量 BGM_FILE
        if bgm_file is None:
            # 尝试从模块获取 BGM_FILE（用于配置播放）
            import prefix_audio
            if hasattr(prefix_audio, 'BGM_FILE') and prefix_audio.BGM_FILE:
                bgm_file = prefix_audio.BGM_FILE
        
        # ✅ 处理 "不选择音乐" 或 None 的情况
        if bgm_file == "不选择音乐" or bgm_file is None:
            # 不选择音乐 → 静音模式
            return self._save_voice_only(speech_file, dance_name)
        
        if bgm_file == "使用内置BGM":  # 使用内置BGM（根目录的 bgm.mp3）
            use_bgm_file = self.bgm_file
        else:
            # 使用自定义BGM文件（来自 bgm/ 目录）
            use_bgm_file = bgm_file
        
        # 如果 use_bgm_file 为 None 或不存在，尝试使用默认BGM
        if use_bgm_file and not os.path.exists(use_bgm_file):
            self.logger.warning(f"BGM文件不存在: {use_bgm_file}，尝试使用默认BGM")
            use_bgm_file = self.bgm_file
        
        # ✅ 如果还是没有BGM，返回纯语音
        if not use_bgm_file or not os.path.exists(use_bgm_file):
            self.logger.warning("没有可用的BGM文件，返回纯语音")
            return self._save_voice_only(speech_file, dance_name)
        
        # ✅ 使用时间戳 + 随机数生成唯一文件名
        import time
        import random
        timestamp = int(time.time() * 1000)
        random_suffix = random.randint(1000, 9999)
        cache_key = self.get_cache_key(dance_name)
        output_file = os.path.join(self.cache_folder, f"prefix_{cache_key}_{timestamp}_{random_suffix}.mp3")

        # # ========== 确定使用的BGM文件 ==========
        # use_bgm_file = bgm_file if bgm_file else self.bgm_file
        
        # # ✅ 打印调试信息
        # self.logger.info(f"使用BGM文件: {use_bgm_file}")
        # if use_bgm_file:
        #     self.logger.info(f"BGM文件是否存在: {os.path.exists(use_bgm_file)}")
        
        # ========== BGM参数校验 ==========
        if use_bgm_file and os.path.exists(use_bgm_file):
            bgm_duration = self._get_audio_duration(use_bgm_file)
            if bgm_duration > 0:
                # 1. 校验起始时间
                if BGM_START_TIME >= bgm_duration:
                    self.logger.warning(
                        f"BGM起始时间({BGM_START_TIME}s)超过文件时长({bgm_duration:.1f}s)，自动调整"
                    )
                    BGM_START_TIME = max(0, bgm_duration - BGM_TOTAL_DURATION - 1)
                
                # 2. 校验起始+时长是否超出
                if BGM_START_TIME + BGM_TOTAL_DURATION > bgm_duration:
                    self.logger.warning(
                        f"BGM起始+时长({BGM_START_TIME + BGM_TOTAL_DURATION:.1f}s)超过文件时长({bgm_duration:.1f}s)，自动调整时长"
                    )
                    BGM_TOTAL_DURATION = bgm_duration - BGM_START_TIME
                    
                # 3. 确保最小时长
                if BGM_TOTAL_DURATION < 1:
                    self.logger.warning(f"BGM时长({BGM_TOTAL_DURATION}s)过短，自动设为3秒")
                    BGM_TOTAL_DURATION = 3.0
        # ========== 校验结束 ==========
        
        for attempt in range(max_retries):
            try:
                # 获取语音时长
                speech_dur = self._get_audio_duration(speech_file)
                
                # 计算语音位置
                if SPEECH_POSITION == "start":
                    speech_start = 0.5
                elif SPEECH_POSITION == "end":
                    speech_start = BGM_TOTAL_DURATION - speech_dur - 0.5
                else:  # middle
                    speech_start = (BGM_TOTAL_DURATION - speech_dur) / 2
                
                speech_start = max(0.5, min(speech_start, BGM_TOTAL_DURATION - speech_dur - 0.5))

                # 构建FFmpeg命令
                speech_abs = os.path.abspath(speech_file)
                bgm_abs = os.path.abspath(use_bgm_file)
                output_abs = os.path.abspath(output_file)
                
                filter_complex = (
                    f"[1:a]atrim={BGM_START_TIME}:{BGM_START_TIME+BGM_TOTAL_DURATION},"
                    f"volume={BGM_VOLUME}[bgm];"
                    f"[0:a]adelay={int(speech_start*1000)}|{int(speech_start*1000)}[speech_delayed];"
                    f"[bgm][speech_delayed]amix=inputs=2:duration=first:"
                    f"dropout_transition={BGM_TOTAL_DURATION}[mixed];"
                    f"[mixed]afade=t=out:st={BGM_TOTAL_DURATION-FADE_OUT_DUR}:d={FADE_OUT_DUR}"
                )
                
                cmd = [
                    'ffmpeg',
                    '-i', speech_abs,
                    '-i', bgm_abs,
                    '-filter_complex', filter_complex,
                    '-c:a', 'libmp3lame',
                    '-b:a', '192k',
                    '-y',
                    output_abs
                ]
                
                result = subprocess.run(cmd, capture_output=True, timeout=60)
                
                if result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                    # 清理旧的同名缓存文件
                    base_name = f"prefix_{cache_key}"
                    for f in os.listdir(self.cache_folder):
                        if f.startswith(base_name) and f != os.path.basename(output_file):
                            try:
                                os.remove(os.path.join(self.cache_folder, f))
                            except:
                                pass
                    return output_file
                
                if attempt < max_retries - 1:
                    time.sleep(1)
                    
            except Exception as e:
                self.logger.error(f"混合音频失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
        
        return None

                # # ✅ 构建FFmpeg命令 - 使用正确的文件路径引用
                # if use_bgm_file and os.path.exists(use_bgm_file):
                #     # 有BGM，使用 BGM_START_TIME 作为起始截取位置
                #     # ✅ 使用绝对路径，避免路径问题
                #     speech_abs = os.path.abspath(speech_file)
                #     bgm_abs = os.path.abspath(use_bgm_file)
                #     output_abs = os.path.abspath(output_file)
                   
                #     filter_complex = (
                #         f"[1:a]atrim={BGM_START_TIME}:{BGM_START_TIME+BGM_TOTAL_DURATION},"
                #         f"volume={BGM_VOLUME}[bgm];"
                #         f"[0:a]adelay={int(speech_start*1000)}|{int(speech_start*1000)}[speech_delayed];"
                #         f"[bgm][speech_delayed]amix=inputs=2:duration=first:"
                #         f"dropout_transition={BGM_TOTAL_DURATION}[mixed];"
                #         f"[mixed]afade=t=out:st={BGM_TOTAL_DURATION-FADE_OUT_DUR}:d={FADE_OUT_DUR}"
                #     )
                    
                #     cmd = [
                #         'ffmpeg',
                #         '-i', speech_abs,
                #         '-i', bgm_abs,
                #         '-filter_complex', filter_complex,
                #         '-c:a', 'libmp3lame',
                #         '-b:a', '192k',
                #         '-y',
                #         output_abs
                #     ]
                # else:
                #     # ✅ 无BGM时也使用绝对路径
                #     speech_abs = os.path.abspath(speech_file)
                #     output_abs = os.path.abspath(output_file)
                    
                #     filter_complex = (
                #         f"[0:a]adelay={int(speech_start*1000)}|{int(speech_start*1000)},"
                #         f"apad=pad_dur={BGM_TOTAL_DURATION},"
                #         f"afade=t=out:st={BGM_TOTAL_DURATION-FADE_OUT_DUR}:d={FADE_OUT_DUR}"
                #     )
                    
                #     cmd = [
                #         'ffmpeg',
                #         '-i', speech_abs,
                #         '-filter_complex', filter_complex,
                #         '-c:a', 'libmp3lame',
                #         '-b:a', '192k',
                #         '-y',
                #         output_abs
                #     ]
                
                # # 执行FFmpeg
                # result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

                # # ✅ 修复：指定 encoding='utf-8'，忽略错误
                # result = subprocess.run(
                #     cmd, 
                #     capture_output=True, 
                #     text=True, 
                #     timeout=30,
                #     encoding='utf-8',  # ✅ 指定 UTF-8 编码
                #     errors='ignore'    # ✅ 忽略无法解码的字符
                # )
                
                # # ✅ 或者使用 binary 模式，手动解码
                # # result = subprocess.run(cmd, capture_output=True, timeout=30)
                # # if result.returncode == 0:
                # #     # 成功时不关心输出
                # #     pass

                # # ✅ 调试：打印完整命令
                # self.logger.debug(f"FFmpeg命令: {' '.join(cmd)}")
                
                # # ✅ 使用二进制模式，避免编码问题
                # result = subprocess.run(
                #     cmd, 
                #     capture_output=True, 
                #     timeout=60  # 增加超时时间
                # )

        #         if result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0:
        #             self.logger.info(f"✅ FFmpeg混合成功: {output_file}")
        #             return output_file
                
        #         # ✅ 提取真正的错误信息
        #         if result.stderr:
        #             try:
        #                 error_str = result.stderr.decode('utf-8', errors='ignore')
        #                 # 查找真正的错误行（不是 ffmpeg 版本信息）
        #                 error_lines = []
        #                 for line in error_str.split('\n'):
        #                     line = line.strip()
        #                     if line and not line.startswith('ffmpeg version') and not line.startswith('  '):
        #                         if 'error' in line.lower() or 'fail' in line.lower():
        #                             error_lines.append(line)
        #                 if error_lines:
        #                     error_msg = error_lines[0][:200]
        #                     self.logger.warning(f"FFmpeg错误: {error_msg}")
        #                 else:
        #                     # 如果没有明显错误，显示最后几行
        #                     last_lines = error_str.split('\n')[-3:]
        #                     self.logger.warning(f"FFmpeg输出: {', '.join([l for l in last_lines if l.strip()])}")
        #             except:
        #                 pass
                
        #         if attempt < max_retries - 1:
        #             time.sleep(1)  # 等待后重试
                    
        #     except subprocess.TimeoutExpired:
        #         self.logger.error(f"FFmpeg超时 (尝试 {attempt + 1}/{max_retries})")
        #         if attempt < max_retries - 1:
        #             time.sleep(1)
        #     except Exception as e:
        #         self.logger.error(f"混合音频失败 (尝试 {attempt + 1}/{max_retries}): {e}")
        #         import traceback
        #         traceback.print_exc()
        #         if attempt < max_retries - 1:
        #             time.sleep(1)
        
        # return None
    
    def _get_audio_duration(self, audio_file: str) -> float:
        """获取音频时长（安全版本）"""
        try:
            cmd = [
                'ffprobe', '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'csv=p=0',
                audio_file
            ]
            # result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

            # ✅ 修复：指定 encoding='utf-8'，忽略错误
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=10,
                encoding='utf-8',
                errors='ignore'
            )


            if result.stdout.strip():
                return float(result.stdout.strip())
        except:
            pass
        return 3.0
    
    def batch_generate(self, dance_names: list, progress_callback=None):
        """批量生成前缀音"""
        results = {}
        
        for i, dance_name in enumerate(dance_names):
            self.logger.info(f"[{i+1}/{len(dance_names)}] 生成前缀音: {dance_name}")
            
            result = self.generate_prefix(dance_name)
            results[dance_name] = result
            
            if progress_callback:
                progress_callback(i + 1, len(dance_names), dance_name, result)
        
        return results
    
    def get_all_dance_names(self):
        """获取所有已缓存的前缀音舞种名称"""
        return [info.get('dance_name', '') for info in self.cache_index.values()]
    
    def clean_cache(self, max_age_days: int = 30):
        """清理过期缓存"""
        try:
            now = datetime.now()
            cleaned = 0
            
            for cache_key, info in list(self.cache_index.items()):
                created_str = info.get('created', '')
                if created_str:
                    try:
                        created = datetime.strptime(created_str, '%Y-%m-%d %H:%M:%S')
                        if (now - created).days > max_age_days:
                            file_path = info.get('file')
                            if file_path and os.path.exists(file_path):
                                os.remove(file_path)
                            del self.cache_index[cache_key]
                            cleaned += 1
                    except:
                        continue
            
            if cleaned > 0:
                self._save_cache_index()
                self.logger.info(f"清理了 {cleaned} 个过期缓存")
            
            return cleaned
        except Exception as e:
            self.logger.error(f"清理缓存失败: {e}")
            return 0
    
    def clear_all_cache(self):
        """清空所有缓存"""
        try:
            for key, info in self.cache_index.items():
                file_path = info.get('file')
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except:
                        pass
            
            self.cache_index.clear()
            self._save_cache_index()
            self.logger.info("已清空所有缓存")
            return True
        except Exception as e:
            self.logger.error(f"清空缓存失败: {e}")
            return False
    
    def get_cache_stats(self) -> dict:
        """获取缓存统计信息"""
        stats = {
            'total': len(self.cache_index),
            'by_engine': {},
            'by_dance': {},
            'total_size_mb': 0
        }
        
        for key, info in self.cache_index.items():
            config = info.get('config', {})
            engine = config.get('engine', 'unknown')
            stats['by_engine'][engine] = stats['by_engine'].get(engine, 0) + 1
            
            dance = info.get('dance_name', 'unknown')
            stats['by_dance'][dance] = stats['by_dance'].get(dance, 0) + 1
            
            file_path = info.get('file')
            if file_path and os.path.exists(file_path):
                stats['total_size_mb'] += os.path.getsize(file_path) / (1024 * 1024)
        
        stats['total_size_mb'] = round(stats['total_size_mb'], 2)
        return stats
    
    def get_cache_by_dance(self, dance_name: str) -> list:
        """获取某个舞种的所有缓存版本"""
        results = []
        for key, info in self.cache_index.items():
            if info.get('dance_name') == dance_name:
                results.append({
                    'key': key,
                    'file': info.get('file'),
                    'created': info.get('created'),
                    'config': info.get('config', {})
                })
        return sorted(results, key=lambda x: x['created'], reverse=True)
    
    def validate_config(self):
        """验证配置参数"""
        errors = []
        
        if not 0 < BGM_VOLUME <= 1.0:
            errors.append(f"BGM_VOLUME 应在 0-1 之间，当前值: {BGM_VOLUME}")
        
        if BGM_TOTAL_DURATION <= 0:
            errors.append(f"BGM_TOTAL_DURATION 应大于 0，当前值: {BGM_TOTAL_DURATION}")
        
        if SPEECH_POSITION not in ['start', 'middle', 'end']:
            errors.append(f"SPEECH_POSITION 应为 start/middle/end，当前值: {SPEECH_POSITION}")
        
        return errors
    
    async def generate_prefix_async(self, dance_name: str) -> Optional[str]:
        """异步生成前缀音"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self.generate_prefix, dance_name)
    
    async def batch_generate_async(self, dance_names: list):
        """异步批量生成"""
        tasks = [self.generate_prefix_async(name) for name in dance_names]
        return await asyncio.gather(*tasks)
    
    def __del__(self):
        """清理资源"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)


# 全局实例
prefix_manager = PrefixAudioManager()