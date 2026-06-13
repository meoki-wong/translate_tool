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

# ========== 翻译语言配置 ==========
# 源语言（识别的语言，也决定 vosk 模型选择）
# 可选: "en", "zh", "ja", "ko", "fr", "de", "es", "ru", "pt", "it"
SOURCE_LANG = os.getenv("SOURCE_LANG", "en")
# 目标语言（翻译输出的语言）
TARGET_LANG = os.getenv("TARGET_LANG", "zh-CN")

# 语言显示名映射
LANG_NAMES = {
    "en": "英语", "zh": "中文", "ja": "日语", "ko": "韩语",
    "fr": "法语", "de": "德语", "es": "西班牙语", "ru": "俄语",
    "pt": "葡萄牙语", "it": "意大利语",
}
# 各厂商语言代码映射
# MyMemory langpair 格式: "src|tgt"
# DeepL target_lang 格式: "ZH"
# 百度 from/to 格式: "en"/"zh"
LANG_CODE_MAP = {
    # source_lang_id -> {provider -> code}
    "en": {"mymemory": "en", "deepl": "EN", "baidu": "en", "ollama": "English"},
    "zh": {"mymemory": "zh-CN", "deepl": "ZH", "baidu": "zh", "ollama": "Chinese"},
    "ja": {"mymemory": "ja", "deepl": "JA", "baidu": "jp", "ollama": "Japanese"},
    "ko": {"mymemory": "ko", "deepl": "KO", "baidu": "kor", "ollama": "Korean"},
    "fr": {"mymemory": "fr", "deepl": "FR", "baidu": "fra", "ollama": "French"},
    "de": {"mymemory": "de", "deepl": "DE", "baidu": "de", "ollama": "German"},
    "es": {"mymemory": "es", "deepl": "ES", "baidu": "spa", "ollama": "Spanish"},
    "ru": {"mymemory": "ru", "deepl": "RU", "baidu": "ru", "ollama": "Russian"},
    "pt": {"mymemory": "pt", "deepl": "PT", "baidu": "pt", "ollama": "Portuguese"},
    "it": {"mymemory": "it", "deepl": "IT", "baidu": "it", "ollama": "Italian"},
}
TARGET_LANG_CODE_MAP = {
    # target_lang_id -> {provider -> code}
    "zh-CN": {"mymemory": "zh-CN", "deepl": "ZH", "baidu": "zh", "ollama": "Chinese"},
    "en": {"mymemory": "en", "deepl": "EN", "baidu": "en", "ollama": "English"},
    "ja": {"mymemory": "ja", "deepl": "JA", "baidu": "jp", "ollama": "Japanese"},
    "ko": {"mymemory": "ko", "deepl": "KO", "baidu": "kor", "ollama": "Korean"},
    "fr": {"mymemory": "fr", "deepl": "FR", "baidu": "fra", "ollama": "French"},
    "de": {"mymemory": "de", "deepl": "DE", "baidu": "de", "ollama": "German"},
    "es": {"mymemory": "es", "deepl": "ES", "baidu": "spa", "ollama": "Spanish"},
    "ru": {"mymemory": "ru", "deepl": "RU", "baidu": "ru", "ollama": "Russian"},
    "pt": {"mymemory": "pt", "deepl": "PT", "baidu": "pt", "ollama": "Portuguese"},
    "it": {"mymemory": "it", "deepl": "IT", "baidu": "it", "ollama": "Italian"},
}

# vosk 模型路径映射（源语言 -> 模型目录名）
VOSK_MODEL_MAP = {
    "en": "vosk-model-en-us-0.22-lgraph",
    # 其他语言模型需自行下载，放入 backend/models/ 目录
    # 下载地址: https://alphacephei.com/vosk/models
    # "zh": "vosk-model-small-cn-0.22",
    # "ja": "vosk-model-small-ja-0.22",
    # "fr": "vosk-model-small-fr-0.22",
    # "de": "vosk-model-small-de-0.22",
    # "es": "vosk-model-small-es-0.22",
    # "ru": "vosk-model-small-ru-0.22",
    # "pt": "vosk-model-small-pt-0.3",
    # "ko": "vosk-model-small-ko-0.12",
}

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
# 可选模型（从差到优）：
#   vosk-model-small-en-us-0.15  (40MB,  WER 10.4, 手机级)
#   vosk-model-en-us-0.22-lgraph (128MB, WER 8.2,  桌面推荐)
#   vosk-model-en-us-0.22        (1.8GB, WER 6.1,  服务器级)
# 下载地址: https://alphacephei.com/vosk/models
VOSK_MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "models",
    VOSK_MODEL_MAP.get(SOURCE_LANG, "vosk-model-small-en-us-0.15")
)
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
