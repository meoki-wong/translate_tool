"""
后端主入口 - 流式音频识别 + 实时翻译 + WebSocket 推送
"""
import asyncio
import signal
import sys
import time
import threading
from pathlib import Path

# 加载 .env 文件（在 config 之前）
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / '.env'
    load_dotenv(env_path)
except ImportError:
    pass

from stream_recognizer import StreamRecognizer
from translator import TranslatorManager
from ws_server import WSServer
import config


class RealtimeTranslator:
    """流式实时翻译主控制器

    架构:
    - vosk 在音频回调中实时识别，结果推入 asyncio.Queue
    - 主循环从队列消费结果:
        partial → 立即推送前端（逐词更新）
        final   → 累积文本，判断句子边界
    - 句子提交条件:
        1. 累积文本超过阈值 + 超时未更新
        2. final 结果且文本足够长
    - 提交时: 翻译 → 推送 final 字幕 → 重置
    """

    def __init__(self):
        self.recognizer = StreamRecognizer()
        self.translator = TranslatorManager()
        self.ws_server = WSServer()
        self._running = False

        # 结果队列（线程安全：audio callback → asyncio loop）
        self._result_queue: asyncio.Queue = asyncio.Queue()

        # 句子累积状态
        self._current_text = ""        # 当前句英文累积
        self._last_text_time = 0       # 最后一次收到文字的时间
        self._last_live_text = ""      # 上次推送的 partial 文本（避免重复）

        # 实时翻译状态
        self._last_translate_time = 0  # 上次发起翻译的时间
        self._last_translated_text = "" # 上次翻译时的英文文本
        self._current_zh = ""          # 当前句的中文翻译
        self._translating = False      # 是否正在翻译中
        self._rate_limited_until = 0   # 被限流直到该时间戳

        # 上下文
        self._context_zh = ""

    def _on_asr_result(self, result_type: str, text: str):
        """vosk 结果回调（在 sounddevice 音频线程中调用）"""
        try:
            self._result_queue.put_nowait((result_type, text))
        except asyncio.QueueFull:
            pass  # 队列满则丢弃

    async def _process_loop(self):
        """主处理循环：消费流式识别结果"""
        print("[Main] 流式处理循环已启动")

        while self._running:
            try:
                result_type, text = await asyncio.wait_for(
                    self._result_queue.get(), timeout=0.3
                )
            except asyncio.TimeoutError:
                # 无新数据 - 检查是否需要提交当前句
                await self._check_sentence_commit()
                continue

            now = time.time()

            if result_type == "partial":
                self._last_text_time = now

                # 避免重复推送相同文本
                if text == self._last_live_text:
                    continue
                self._last_live_text = text
                self._current_text = text

                # 实时推送 partial 英文到前端
                await self.ws_server.broadcast_partial(text, self._current_zh)

                # 定期发起实时翻译（跳过被限流时）
                if (not self._translating
                        and now > self._rate_limited_until
                        and len(text) > 3
                        and (now - self._last_translate_time) > config.LIVE_TRANSLATE_INTERVAL
                        and text != self._last_translated_text):
                    self._last_translate_time = now
                    self._translating = True
                    asyncio.create_task(self._live_translate(text))

            elif result_type == "final":
                self._last_text_time = now

                # 累积 final 文本
                if self._current_text and text:
                    self._current_text += " " + text
                else:
                    self._current_text = text
                self._last_live_text = self._current_text

                # 推送更新后的文本
                await self.ws_server.broadcast_partial(self._current_text, self._current_zh)

                # 判断是否提交句子: 文本够长且已有内容
                word_count = len(self._current_text.split())
                if word_count >= 5:
                    await self._commit_sentence()

        print("[Main] 处理循环结束")

    async def _check_sentence_commit(self):
        """检查是否需要提交当前句子（超时提交）"""
        if not self._current_text:
            return

        now = time.time()
        if (now - self._last_text_time) > config.SENTENCE_COMMIT_TIMEOUT:
            await self._commit_sentence()

    async def _commit_sentence(self):
        """提交当前句子：翻译 + 推送 + 重置"""
        text = self._current_text.strip()
        if not text:
            return

        print(f"[Main] 提交句子: {text}")

        # 翻译
        try:
            zh_text = await self.translator.translate(text, self._context_zh)
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "Too Many" in err_str:
                self._rate_limited_until = time.time() + 30
                print(f"[Main] 翻译服务被限流 30s")
            else:
                print(f"[Main] 翻译失败: {e}")
            zh_text = "[翻译失败]"

        print(f"[Main] 翻译结果: {zh_text}")

        # 更新中文上下文（保留最近 3 句）
        if self._context_zh:
            parts = self._context_zh.split("。")[-3:]
            self._context_zh = "。".join(parts)
        self._context_zh += zh_text + "。"

        # 推送已提交字幕到前端
        await self.ws_server.broadcast(text, zh_text)

        # 重置句子状态
        self._current_text = ""
        self._last_live_text = ""
        self._current_zh = ""
        self._last_translated_text = ""
        self._last_translate_time = 0
        self._translating = False
        self.recognizer.reset()

    async def _live_translate(self, text: str):
        """实时翻译 partial 文本（后台任务）"""
        try:
            # 只翻译最后 200 个字符，避免请求过大
            short_text = text[-200:] if len(text) > 200 else text
            zh = await self.translator.translate(short_text, self._context_zh)
            self._current_zh = zh
            self._last_translated_text = text
            # 推送带翻译的 partial
            await self.ws_server.broadcast_partial(text, zh)
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "Too Many" in err_str:
                # 被限流，暂停 30 秒不再发起实时翻译
                self._rate_limited_until = time.time() + 30
                print(f"[Main] 翻译服务被限流，暂停实时翻译 30s")
            else:
                print(f"[Main] 实时翻译失败: {e}")
        finally:
            self._translating = False

    async def _handle_command(self, data, websocket):
        """处理客户端发来的命令"""
        action = data.get("action")
        if action == "switch_provider":
            provider = data.get("provider")
            if provider:
                try:
                    await self.translator.switch_provider(provider)
                    config.TRANSLATOR_PROVIDER = provider
                    print(f"[Main] 翻译厂商已切换: {provider}")
                    await self.ws_server.broadcast_status(
                        "provider_changed",
                        f"已切换到 {provider}"
                    )
                except Exception as e:
                    print(f"[Main] 切换翻译厂商失败: {e}")
                    await self.ws_server.broadcast_status(
                        "error", f"切换失败: {e}"
                    )

    async def run(self):
        """启动所有服务"""
        print("=" * 50)
        print("  Mac 实时音频翻译工具 (流式)")
        print(f"  翻译厂商: {config.TRANSLATOR_PROVIDER}")
        print(f"  ASR 引擎: vosk (流式)")
        print("=" * 50)

        self._running = True

        # 1. 启动 WebSocket 服务
        self.ws_server.set_command_handler(self._handle_command)
        await self.ws_server.start()

        # 2. 初始化翻译器
        await self.translator.init()

        # 3. 加载 vosk 模型
        await asyncio.to_thread(self.recognizer.load_model)

        # 4. 设置结果回调
        self.recognizer.set_result_callback(self._on_asr_result)

        # 5. 启动流式识别（含音频捕获）
        try:
            self.recognizer.start()
        except RuntimeError as e:
            print(f"[Main] 流式识别启动失败: {e}")
            await self.ws_server.broadcast_status("error", str(e))

        # 6. 启动处理循环
        await self._process_loop()

    async def stop(self):
        """停止所有服务"""
        print("\n[Main] 正在停止...")
        self._running = False
        self.recognizer.stop()
        await self.translator.close()
        await self.ws_server.stop()
        print("[Main] 已停止")


async def main():
    app = RealtimeTranslator()

    loop = asyncio.get_running_loop()

    def _signal_handler():
        asyncio.ensure_future(app.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
