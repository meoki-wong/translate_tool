"""
配置文件 - 全局配置项
"""
import os

# ========== 翻译服务配置 ==========
# 可选值: "hunyuan", "deepl", "baidu", "openai", "mymemory", "ollama"
TRANSLATOR_PROVIDER = os.getenv("TRANSLATOR_PROVIDER", "mymemory")

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

# Ollama 本地模型配置
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2:7b-instruct")

# ========== 音频捕获配置 ==========
# BlackHole 设备名称关键词（用于自动匹配）
BLACKHOLE_DEVICE_NAME = "BlackHole"
SAMPLE_RATE = 16000  # 采样率
CHANNELS = 1         # 单声道
BLOCK_DURATION = 0.1 # 每个音频块时长（秒）

# ========== 流式 ASR 配置 (vosk) ==========
# vosk 模型路径（相对于 backend 目录）
VOSK_MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "vosk-model-small-en-us-0.15")
# 句子提交超时（秒）- 多久没有新文字就提交当前句
SENTENCE_COMMIT_TIMEOUT = 1.5
# 实时翻译间隔（秒）- 每隔多久对 partial 文本做一次翻译
LIVE_TRANSLATE_INTERVAL = 3.0

# ========== WebSocket 配置 ==========
WS_HOST = "localhost"
WS_PORT = 8765

# ========== 翻译缓存配置 ==========
TRANSLATION_CACHE_SIZE = 500  # LRU 缓存大小
