# 项目依赖清单


## 📦 核心依赖
txt


<pr># requirements.txt

\# 音频播放引擎
pygame>=2.5.0          # 音频播放、混音器管理

\# 音频处理
librosa>=0.10.0        # 变速变调、BPM检测、音频分析
soundfile>=0.12.0      # 高质量音频文件读写（WAV/FLAC）
numpy>=1.24.0          # 数值计算基础库

\# 音频元数据
mutagen>=1.47.0        # 读取音频文件元信息（时长、比特率等）

\# 音频生成
edge-tts gtts pyttsx3  #语音生成

\# GUI相关
Pillow>=10.0.0         # 图像处理（图标、封面）

</pr>

## 🔧 可选依赖
txt

<pr>
# requirements-optional.txt

\# 拖放支持
tkinterdnd2>=0.3.0     # 支持文件拖拽到窗口
</pr>

## 📥 一键安装
**完整安装（包含可选依赖）**

bash

`pip install -r requirements.txt -r requirements-optional.txt`

**最小安装（仅核心功能）**

bash

`pip install -r requirements.txt`

## 🖥️ 系统依赖

|依赖|	说明|	备注|
|:---|:---|:---|
|Python 3.8+	|编程语言运行时|	推荐3.10+|
|Tkinter	|GUI框架	|Python自带|
|FFmpeg	|音频解码（可选）	|某些格式需要|

## 📊 依赖关系图
text

<pr>
ballroom_player.py
├── pygame (音频播放)
│   └── SDL (底层音频库)
├── librosa (音频处理)
│   ├── numpy (数值计算)
│   ├── scipy (科学计算)
│   └── soundfile (文件读写)
│       └── libsndfile (底层音频库)
├── mutagen (元数据)
├── Pillow (图像)
└── tkinter (GUI)
    └── tkinterdnd2 (可选，拖放支持)
</pr>
   


## ⚡ 快速安装命令

Windows

bash

`pip install pygame librosa soundfile numpy mutagen Pillow tkinterdnd2`

macOS

bash

`pip3 install pygame librosa soundfile numpy mutagen Pillow tkinterdnd2`

Linux (Ubuntu/Debian)

bash

`sudo apt-get install python3-tk libsndfile1
pip3 install pygame librosa soundfile numpy mutagen Pillow tkinterdnd2`














