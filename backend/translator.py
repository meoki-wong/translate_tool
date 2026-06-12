"""
翻译模块 - 可插拔多厂商架构（策略模式）
支持: 混元翻译(默认)、DeepL、百度、OpenAI、MyMemory、Ollama(本地)
"""
import abc
import json
import hashlib
import time
from collections import OrderedDict
from typing import Optional

import httpx

import config


# ==================== 抽象基类 ====================

class TranslatorBase(abc.ABC):
    """翻译器抽象基类"""

    @abc.abstractmethod
    async def translate(self, text: str, context: str = "") -> str:
        """
        翻译文本

        Args:
            text: 待翻译的英文文本
            context: 上下文（前几句翻译结果），用于提高连贯性

        Returns:
            翻译后的中文文本
        """
        ...

    @abc.abstractmethod
    async def close(self):
        """释放资源"""
        ...


# ==================== 翻译缓存 ====================

class TranslationCache:
    """LRU 翻译缓存"""

    def __init__(self, max_size: int = 500):
        self._cache: OrderedDict = OrderedDict()
        self._max_size = max_size

    def get(self, key: str) -> Optional[str]:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, key: str, value: str):
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)
        self._cache[key] = value

    @staticmethod
    def make_key(text: str, provider: str) -> str:
        return f"{provider}:{hashlib.md5(text.encode()).hexdigest()}"


# ==================== 混元翻译（默认） ====================

class HunyuanTranslator(TranslatorBase):
    """
    腾讯混元翻译 - 基于混元大模型 ChatCompletions API
    原腾讯翻译君已于 2025-04-15 下线，迁移至混元大模型
    """

    def __init__(self):
        from tencentcloud.common import credential
        from tencentcloud.hunyuan.v20230901 import hunyuan_client, models

        cred = credential.Credential(
            config.HUNYUAN_SECRET_ID,
            config.HUNYUAN_SECRET_KEY,
        )
        self._client = hunyuan_client.HunyuanClient(
            cred, config.HUNYUAN_REGION
        )
        self._models = models

    async def translate(self, text: str, context: str = "") -> str:
        import asyncio
        return await asyncio.to_thread(self._translate_sync, text, context)

    def _make_msg(self, role: str, content: str):
        msg = self._models.Message()
        msg.Role = role
        msg.Content = content
        return msg

    def _translate_sync(self, text: str, context: str = "") -> str:
        req = self._models.ChatCompletionsRequest()
        req.Model = config.HUNYUAN_MODEL
        # 精简 prompt，减少 token 处理时间
        system_prompt = "英译中，只输出译文，不解释。"
        if context:
            system_prompt += f" 前文：{context[:100]}"

        messages = [
            self._make_msg("system", system_prompt),
            self._make_msg("user", text),
        ]
        req.Messages = messages

        resp = self._client.ChatCompletions(req)
        result = resp.Choices[0].Message.Content
        return result.strip()

    async def close(self):
        pass


# ==================== MyMemory（开发调试用） ====================

class MyMemoryTranslator(TranslatorBase):
    """MyMemory 翻译 - 无需注册，适合开发调试"""

    BASE_URL = "https://api.mymemory.translated.net/get"

    def __init__(self):
        self._client = httpx.AsyncClient(timeout=10)

    async def translate(self, text: str, context: str = "") -> str:
        resp = await self._client.get(
            self.BASE_URL,
            params={"q": text, "langpair": "en|zh-CN"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("responseData", {}).get("translatedText", "")

    async def close(self):
        await self._client.aclose()


# ==================== DeepL（备选骨架） ====================

class DeepLTranslator(TranslatorBase):
    """DeepL 翻译 - 需要 API Key"""

    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url="https://api-free.deepl.com/v2",
            headers={"Authorization": f"DeepL-Auth-Key {config.DEEPL_API_KEY}"},
            timeout=10,
        )

    async def translate(self, text: str, context: str = "") -> str:
        resp = await self._client.post(
            "/translate",
            data={
                "text": text,
                "target_lang": "ZH",
                "source_lang": "EN",
                "context": context,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["translations"][0]["text"]

    async def close(self):
        await self._client.aclose()


# ==================== 百度翻译（备选骨架） ====================

class BaiduTranslator(TranslatorBase):
    """百度翻译 - 需要 APP_ID 和 SECRET_KEY"""

    BASE_URL = "https://fanyi-api.baidu.com/api/trans/vip/translate"

    def __init__(self):
        self._client = httpx.AsyncClient(timeout=10)

    async def translate(self, text: str, context: str = "") -> str:
        import hashlib
        import random

        salt = str(random.randint(32768, 65536))
        sign_str = config.BAIDU_APP_ID + text + salt + config.BAIDU_SECRET_KEY
        sign = hashlib.md5(sign_str.encode()).hexdigest()

        resp = await self._client.get(
            self.BASE_URL,
            params={
                "q": text,
                "from": "en",
                "to": "zh",
                "appid": config.BAIDU_APP_ID,
                "salt": salt,
                "sign": sign,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("trans_result", [])
        return "\n".join(r["dst"] for r in results)

    async def close(self):
        await self._client.aclose()


# ==================== OpenAI（备选骨架） ====================

class OpenAITranslator(TranslatorBase):
    """OpenAI GPT 翻译 - 需要 API Key"""

    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url="https://api.openai.com/v1",
            headers={
                "Authorization": f"Bearer {config.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )

    async def translate(self, text: str, context: str = "") -> str:
        system_prompt = (
            "You are a professional English-to-Chinese translator. "
            "Translate the given English text into natural, fluent Chinese. "
            "Output ONLY the translation, nothing else."
        )
        if context:
            system_prompt += f"\nPrevious context for reference: {context}"

        resp = await self._client.post(
            "/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                "temperature": 0.3,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    async def close(self):
        await self._client.aclose()


# ==================== Ollama（本地部署） ====================

class OllamaTranslator(TranslatorBase):
    """Ollama 本地模型翻译 - 无需联网，通过 OpenAI 兼容 API"""

    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url=config.OLLAMA_BASE_URL,
            headers={
                # 跳过 ngrok 免费版浏览器拦截页
                "ngrok-skip-browser-warning": "true",
            },
            timeout=60,  # 本地模型可能较慢
        )

    async def translate(self, text: str, context: str = "") -> str:
        system_prompt = "英译中，只输出译文，不解释。"
        if context:
            system_prompt += f" 前文：{context[:100]}"

        resp = await self._client.post(
            "/api/chat",
            json={
                "model": config.OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                "stream": False,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"].strip()

    async def close(self):
        await self._client.aclose()


# ==================== 翻译器工厂 ====================

_TRANSLATOR_MAP = {
    "hunyuan": HunyuanTranslator,
    "mymemory": MyMemoryTranslator,
    "deepl": DeepLTranslator,
    "baidu": BaiduTranslator,
    "openai": OpenAITranslator,
    "ollama": OllamaTranslator,
}

# 降级顺序：主厂商失败时依次尝试
# 已禁用自动降级 - 选什么用什么


class TranslatorManager:
    """翻译管理器 - 支持运行时切换，无自动降级"""

    def __init__(self):
        self._cache = TranslationCache(config.TRANSLATION_CACHE_SIZE)
        self._primary: Optional[TranslatorBase] = None
        self._provider_name = config.TRANSLATOR_PROVIDER

    async def init(self):
        """初始化主翻译器"""
        cls = _TRANSLATOR_MAP.get(self._provider_name)
        if cls is None:
            raise ValueError(
                f"未知的翻译厂商: {self._provider_name}。"
                f"可选: {list(_TRANSLATOR_MAP.keys())}"
            )
        self._primary = cls()
        print(f"[Translator] 初始化翻译厂商: {self._provider_name}")

    async def translate(self, text: str, context: str = "") -> str:
        """翻译文本（带缓存，无降级）"""
        if not text.strip():
            return ""

        # 检查缓存
        cache_key = TranslationCache.make_key(text, self._provider_name)
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        # 直接调用选定的厂商，失败则抛异常
        result = await self._primary.translate(text, context)
        self._cache.put(cache_key, result)
        return result

    async def close(self):
        if self._primary:
            await self._primary.close()

    async def switch_provider(self, provider_name: str):
        """运行时切换翻译厂商"""
        cls = _TRANSLATOR_MAP.get(provider_name)
        if cls is None:
            raise ValueError(
                f"未知的翻译厂商: {provider_name}。"
                f"可选: {list(_TRANSLATOR_MAP.keys())}"
            )
        # 关闭旧的
        if self._primary:
            await self._primary.close()
        # 创建新的
        self._primary = cls()
        self._provider_name = provider_name
        print(f"[Translator] 已切换到: {provider_name}")
