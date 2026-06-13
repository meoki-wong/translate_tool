"""
配置文件 - 全局配置项
"""
import os
from pathlib import Path

# 自动加载 .env 文件
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent.parent / '.env'
    load_dotenv(_env_path)
except ImportError:
    pass

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

# ========== 音频捕获配置（跨平台） ==========
SAMPLE_RATE = 16000  # 采样率
CHANNELS = 1         # 单声道（vosk 需要单声道）
BLOCK_DURATION = 0.1 # 每个音频块时长（秒）
# macOS: BlackHole 虚拟声卡（需 brew install blackhole-2ch）
# Windows: WASAPI 回环（原生支持，无需额外安装）

# ========== 流式 ASR 配置 (vosk) ==========
# vosk 模型路径（相对于 backend 目录）
VOSK_MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "vosk-model-small-en-us-0.15")
# 句子提交超时（秒）- 多久没有新文字就提交当前句
SENTENCE_COMMIT_TIMEOUT = 0.4
# 句子提交词数 - final 累积超过此词数时立即提交
COMMIT_WORD_COUNT = 4
# partial 强制提交阈值 - partial 文本达到此词数时强制提交并重置识别器
# 防止连续说话时文本无限累积（核心！）
# 值越小越早切断，避免产生 20+ 词的超长片段
PARTIAL_COMMIT_THRESHOLD = 6
# 投机翻译：partial 文本达到此词数时提前发起翻译（不等句子完成）
SPECULATIVE_WORD_COUNT = 3
# 投机翻译最小间隔（秒）
SPECULATIVE_INTERVAL = 0.25
# 投机翻译复用阈值：提交时投机翻译覆盖率 >= 此值则直接复用（词级前缀判定）
SPECULATIVE_REUSE_RATIO = 0.85
# 投机翻译并发上限：同一时刻最多多少个翻译请求在飞（0 或负数 = 无上限）
# 本地 Ollama 是单 GPU 串行处理，过多并发会在服务端排队，
# 反而拉长最终提交翻译的等待时间。建议 4-6。
SPECULATIVE_MAX_INFLIGHT = 4

# ========== WebSocket 配置 ==========
WS_HOST = "localhost"
WS_PORT = 8765

# ========== 翻译缓存配置 ==========
TRANSLATION_CACHE_SIZE = 500  # LRU 缓存大小
