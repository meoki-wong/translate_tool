"""
翻译模块 - 可插拔多厂商架构（策略模式）
支持: 混元翻译(默认)、DeepL、百度、OpenAI、MyMemory、Ollama(本地)
"""
import abc
import asyncio
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
    async def translate(self, text: str, context: str = "",
                         source_lang: str = "", target_lang: str = "") -> str:
        """
        翻译文本

        Args:
            text: 待翻译文本
            context: 上下文（前几句翻译结果），用于提高连贯性
            source_lang: 源语言代码（如 "en"），空则用 config 默认
            target_lang: 目标语言代码（如 "zh-CN"），空则用 config 默认

        Returns:
            翻译后的文本
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
    def make_key(text: str, provider: str, source_lang: str = "", target_lang: str = "") -> str:
        lang_suffix = f":{source_lang}->{target_lang}" if source_lang or target_lang else ""
        return f"{provider}{lang_suffix}:{hashlib.md5(text.encode()).hexdigest()}"


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

    async def translate(self, text: str, context: str = "",
                         source_lang: str = "", target_lang: str = "") -> str:
        import asyncio
        return await asyncio.to_thread(self._translate_sync, text, context, source_lang, target_lang)

    def _make_msg(self, role: str, content: str):
        msg = self._models.Message()
        msg.Role = role
        msg.Content = content
        return msg

    def _translate_sync(self, text: str, context: str = "",
                         source_lang: str = "", target_lang: str = "") -> str:
        src = source_lang or config.SOURCE_LANG
        tgt = target_lang or config.TARGET_LANG
        src_name = config.LANG_NAMES.get(src, src)
        tgt_name = config.LANG_NAMES.get(tgt.replace("-CN", ""), tgt)
        req = self._models.ChatCompletionsRequest()
        req.Model = config.HUNYUAN_MODEL
        system_prompt = (
            f"你是专业{src_name}-{tgt_name}翻译。将{src_name}翻译为自然流畅的{tgt_name}。"
            "只输出译文，不要解释、不要加引号、不要加注释。"
        )
        if context:
            system_prompt += f" 前文参考：{context[:100]}"

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
    MAX_CHARS = 500  # MyMemory 单次请求上限

    def __init__(self):
        self._client = httpx.AsyncClient(timeout=15)

    @staticmethod
    def _clean_text(text: str) -> str:
        """清理文本：去除多余空格和换行"""
        import re
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    async def translate(self, text: str, context: str = "",
                         source_lang: str = "", target_lang: str = "") -> str:
        text = self._clean_text(text)
        if not text:
            return ""

        # 超长文本截断（MyMemory 限制 500 字符）
        if len(text) > self.MAX_CHARS:
            text = text[:self.MAX_CHARS]

        src = source_lang or config.SOURCE_LANG
        tgt = target_lang or config.TARGET_LANG
        src_code = config.LANG_CODE_MAP.get(src, {}).get("mymemory", src)
        tgt_code = config.TARGET_LANG_CODE_MAP.get(tgt, {}).get("mymemory", tgt)

        resp = await self._client.get(
            self.BASE_URL,
            params={"q": text, "langpair": f"{src_code}|{tgt_code}"},
        )
        resp.raise_for_status()
        data = resp.json()
        result = data.get("responseData", {}).get("translatedText", "")
        # MyMemory 有时会返回大写或带奇怪符号，清理一下
        if result and result == result.upper() and len(result) > 3:
            result = result.capitalize()
        return result

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

    async def translate(self, text: str, context: str = "",
                         source_lang: str = "", target_lang: str = "") -> str:
        src = source_lang or config.SOURCE_LANG
        tgt = target_lang or config.TARGET_LANG
        src_code = config.LANG_CODE_MAP.get(src, {}).get("deepl", "EN")
        tgt_code = config.TARGET_LANG_CODE_MAP.get(tgt, {}).get("deepl", "ZH")
        resp = await self._client.post(
            "/translate",
            data={
                "text": text,
                "target_lang": tgt_code,
                "source_lang": src_code,
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

    async def translate(self, text: str, context: str = "",
                         source_lang: str = "", target_lang: str = "") -> str:
        import hashlib
        import random

        src = source_lang or config.SOURCE_LANG
        tgt = target_lang or config.TARGET_LANG
        src_code = config.LANG_CODE_MAP.get(src, {}).get("baidu", src)
        tgt_code = config.TARGET_LANG_CODE_MAP.get(tgt, {}).get("baidu", tgt)

        salt = str(random.randint(32768, 65536))
        sign_str = config.BAIDU_APP_ID + text + salt + config.BAIDU_SECRET_KEY
        sign = hashlib.md5(sign_str.encode()).hexdigest()

        resp = await self._client.get(
            self.BASE_URL,
            params={
                "q": text,
                "from": src_code,
                "to": tgt_code,
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

    async def translate(self, text: str, context: str = "",
                         source_lang: str = "", target_lang: str = "") -> str:
        src = source_lang or config.SOURCE_LANG
        tgt = target_lang or config.TARGET_LANG
        src_name = config.LANG_NAMES.get(src, src)
        tgt_name = config.LANG_NAMES.get(tgt.replace("-CN", ""), tgt)
        system_prompt = (
            f"You are a professional {src_name}-to-{tgt_name} translator. "
            f"Translate the given {src_name} text into natural, fluent {tgt_name}. "
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
    """Ollama 本地模型翻译 - 无需联网，通过 Ollama API"""

    MAX_RETRIES = 2  # 最多重试次数

    def __init__(self):
        # 本地直连（localhost / 127.0.0.1）使用长驻 client 以复用 keep-alive；
        # ngrok 等远程场景仍每次新建 client，避免连接池失效。
        self._base_url = config.OLLAMA_BASE_URL
        self._headers = {"ngrok-skip-browser-warning": "true"}
        self._is_local = (
            "localhost" in self._base_url
            or "127.0.0.1" in self._base_url
            or "10.1." in self._base_url
            or "192.168." in self._base_url
            or "172.16." in self._base_url
            or "172.17." in self._base_url
            or "172.18." in self._base_url
            or "172.19." in self._base_url
            or "172.2" in self._base_url
            or "172.3" in self._base_url
        )
        self._client: Optional[httpx.AsyncClient] = (
            httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers,
                timeout=60,
            ) if self._is_local else None
        )

    async def translate(self, text: str, context: str = "",
                         source_lang: str = "", target_lang: str = "") -> str:
        src = source_lang or config.SOURCE_LANG
        tgt = target_lang or config.TARGET_LANG
        src_name = config.LANG_CODE_MAP.get(src, {}).get("ollama", src)
        tgt_name = config.TARGET_LANG_CODE_MAP.get(tgt, {}).get("ollama", tgt)
        system_prompt = (
            f"你是严格的{src_name}-{tgt_name}翻译机。规则：\n"
            f"1. 仅输出用户输入{src_name}文本的{tgt_name}翻译，一句一译。\n"
            "2. 不要解释、不要扩展、不要补充、不要联想。\n"
            "3. 不要加引号、括号、标题、标号或标记。\n"
            "4. 输入即使不完整也只译已有内容，不要猜测下文。\n"
            "5. 输出不得超过一行。"
        )
        if context:
            system_prompt += f"\n前文参考：{context[:100]}"

        payload = {
            "model": config.OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "stream": True,
            # 防幻觉 / 防自由发挥：限制生成长度、降低随机性、设置停词
            "options": {
                "temperature": 0.2,
                "top_p": 0.8,
                "num_predict": 160,
                "stop": ["\n\n", "User:", "用户：", "译文：", "原文："],
            },
        }

        last_err = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                # 构建流式请求上下文
                if self._is_local and self._client is not None:
                    stream_ctx = self._client.stream(
                        "POST", "/api/chat", json=payload,
                    )
                else:
                    client = httpx.AsyncClient(
                        base_url=self._base_url,
                        headers=self._headers,
                        timeout=60,
                    )
                    stream_ctx = client.stream(
                        "POST", "/api/chat", json=payload,
                    )
                # 流式读取：拼接所有 content chunk，遇到 done 即止
                result_parts = []
                async with stream_ctx as resp:
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if chunk.get("done"):
                            break
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            result_parts.append(content)
                if not self._is_local:
                    await client.aclose()
                result = "".join(result_parts).strip()
                # 后处理：截到第一段，防止模型在译文后举例/补充/联想
                if "\n\n" in result:
                    result = result.split("\n\n", 1)[0].strip()
                # 进一步取第一行（语音翻译场景不需多行）
                if "\n" in result:
                    first_line = result.split("\n", 1)[0].strip()
                    if first_line:
                        result = first_line
                # 清理常见的大模型输出瑕疵
                if result.startswith('"') and result.endswith('"'):
                    result = result[1:-1]
                if result.startswith('「') and result.endswith('」'):
                    result = result[1:-1]
                # 异常长度保护：中文译文超过输入字符 6 倍认为幻觉，丢弃并以空串兑现
                if len(text) > 0 and len(result) > len(text) * 6:
                    print(f"[Ollama] 警告：输出过长可能幻觉（输入{len(text)}字/输出{len(result)}字）丢弃")
                    return ""
                return result
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                last_err = e
                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(1)  # 等待 1s 后重试
                    continue
                raise

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None


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

    async def translate(self, text: str, context: str = "",
                         source_lang: str = "", target_lang: str = "") -> str:
        """翻译文本（带缓存，无降级）"""
        if not text.strip():
            return ""

        src = source_lang or config.SOURCE_LANG
        tgt = target_lang or config.TARGET_LANG

        # 检查缓存
        cache_key = TranslationCache.make_key(text, self._provider_name, src, tgt)
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        # 直接调用选定的厂商，失败则抛异常
        result = await self._primary.translate(text, context, src, tgt)
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
