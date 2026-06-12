"""
配置文件 - 全局配置项
"""
import os

# ========== 翻译服务配置 ==========
# 可选值: "hunyuan", "deepl", "baidu", "openai", "mymemory"
TRANSLATOR_PROVIDER = os.getenv("TRANSLATOR_PROVIDER", "hunyuan")

# 腾讯混元翻译配置
HUNYUAN_SECRET_ID = os.getenv("HUNYUAN_SECRET_ID", "")
HUNYUAN_SECRET_KEY = os.getenv("HUNYUAN_SECRET_KEY", "")
HUNYUAN_MODEL = "hunyuan-turbo-latest"
HUNYUAN_REGION = "ap-guangzhou"

# DeepL 配置（备选）
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY", "")

# 百度翻译配置（备选）
BAIDU_APP_ID = os.getenv("BAIDU_APP_ID", "")
BAIDU_SECRET_KEY = os.getenv("BAIDU_SECRET_KEY", "")

# OpenAI 配置（备选）
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ========== 音频捕获配置 ==========
# BlackHole 设备名称关键词（用于自动匹配）
BLACKHOLE_DEVICE_NAME = "BlackHole"
SAMPLE_RATE = 16000  # 采样率
CHANNELS = 1         # 单声道
BLOCK_DURATION = 0.1 # 每个音频块时长（秒）

# ========== VAD 配置 ==========
VAD_ENERGY_THRESHOLD = 500    # 能量阈值（根据实际环境调整）
VAD_SILENCE_DURATION = 0.5    # 静音持续时间（秒）触发分段
MIN_SEGMENT_DURATION = 0.8    # 最小音频段时长（秒）
MAX_SEGMENT_DURATION = 5.0    # 最大音频段时长（秒）

# ========== Whisper 配置 ==========
WHISPER_MODEL_SIZE = "base"   # tiny, base, small, medium, large-v3
WHISPER_DEVICE = "auto"       # auto, cpu, cuda
WHISPER_COMPUTE_TYPE = "int8" # int8, float16, float32
WHISPER_LANGUAGE = "en"       # 源语言

# ========== WebSocket 配置 ==========
WS_HOST = "localhost"
WS_PORT = 8765

# ========== 翻译缓存配置 ==========
TRANSLATION_CACHE_SIZE = 500  # LRU 缓存大小
