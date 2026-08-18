# 项目依赖清单



## Python 环境

- Python 3.8 或更高版本



## Python 库（使用 pip 安装）

bash
```
pip install -r requirements.txt
```




# 外部程序（必须单独安装）

## FFmpeg（音频处理核心工具）

1，下载 FFmpeg：https://ffmpeg.org/download.html



2，Windows 用户选择 Windows Builds（如 gyan.dev 或 BtbN 的版本）




3，解压到本地目录：（例如 C:\\ffmpeg）（请根据实际情况调整）


4，将 bin 文件夹路径添加到系统 PATH 环境变量



5，或者在代码中设置 FFMPEG\_PATH 变量指向 ffmpeg.exe 的完整路径



**验证安装**

在命令行运行以下命令，确认 FFmpeg 已正确安装：



bash
```
ffmpeg -version
```
**网络要求**

- edge\_tts 和 gTTS 需要互联网连接（调用在线语音服务）



**Windows 特殊说明**

- pyttsx3 依赖 Windows SAPI 5 语音引擎（系统自带）



- 如果使用精简版 Windows，可能需要安装语音包























