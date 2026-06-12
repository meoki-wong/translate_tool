"""
后端主入口 - 串联音频捕获、语音识别、翻译和 WebSocket 推送
"""
import asyncio
import signal
import sys
import threading
from pathlib import Path

# 加载 .env 文件（在 config 之前）
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / '.env'
    load_dotenv(env_path)
except ImportError:
    pass

from audio_capture import AudioCapture
from speech_recognizer import SpeechRecognizer
from translator import TranslatorManager
from ws_server import WSServer
import config


class RealtimeTranslator:
    """实时翻译主控制器"""

    def __init__(self):
        self.audio_capture = AudioCapture()
        self.recognizer = SpeechRecognizer()
        self.translator = TranslatorManager()
        self.ws_server = WSServer()
        self._running = False
        self._context_zh = ""  # 中文翻译上下文

    async def _process_loop(self):
        """主处理循环：从音频队列取数据 -> 识别 -> 翻译 -> 推送"""
        print("[Main] 处理循环已启动")

        while self._running:
            # 从队列获取音频段
            segment_data = await asyncio.to_thread(
                self.audio_capture.get_segment, timeout=1.0
            )

            if segment_data is None:
                continue

            audio_segment, duration = segment_data

            # 语音识别
            import time as _t
            t0 = _t.time()
            await self.ws_server.broadcast_status("recognizing", "正在识别...")
            try:
                result = await asyncio.to_thread(
                    self.recognizer.transcribe, audio_segment, duration
                )
            except Exception as e:
                print(f"[Main] 语音识别失败: {e}")
                continue

            en_text = result["text"]
            if not en_text:
                continue

            t1 = _t.time()
            print(f"[Main] 识别 ({t1-t0:.2f}s): {en_text}")

            # ★ 识别完成立即推送英文到前端（不等翻译）
            await self.ws_server.broadcast(en_text, "", duration)

            # 翻译
            await self.ws_server.broadcast_status("translating", "正在翻译...")
            try:
                zh_text = await self.translator.translate(en_text, self._context_zh)
            except Exception as e:
                print(f"[Main] 翻译失败: {e}")
                zh_text = f"[翻译失败]"

            t2 = _t.time()
            print(f"[Main] 翻译 ({t2-t1:.2f}s): {zh_text}")

            # 更新中文上下文（保留最近 3 句）
            if self._context_zh:
                parts = self._context_zh.split("。")[-3:]
                self._context_zh = "。".join(parts)
            self._context_zh += zh_text + "。"

            # 推送翻译结果（更新同一条字幕）
            await self.ws_server.broadcast(en_text, zh_text, duration)

            print(f"[Main] 总延迟: {t2-t0:.2f}s")

    async def run(self):
        """启动所有服务"""
        print("=" * 50)
        print("  Mac 实时音频翻译工具")
        print(f"  翻译厂商: {config.TRANSLATOR_PROVIDER}")
        print(f"  Whisper 模型: {config.WHISPER_MODEL_SIZE}")
        print("=" * 50)

        self._running = True

        # 1. 启动 WebSocket 服务
        await self.ws_server.start()

        # 2. 初始化翻译器
        await self.translator.init()

        # 3. 加载 Whisper 模型
        await asyncio.to_thread(self.recognizer.load_model)

        # 4. 启动音频捕获
        try:
            self.audio_capture.start()
        except RuntimeError as e:
            print(f"[Main] 音频捕获启动失败: {e}")
            await self.ws_server.broadcast_status("error", str(e))
            # 不退出，WebSocket 仍然可以运行用于调试

        # 5. 启动处理循环
        await self._process_loop()

    async def stop(self):
        """停止所有服务"""
        print("\n[Main] 正在停止...")
        self._running = False
        self.audio_capture.stop()
        await self.translator.close()
        await self.ws_server.stop()
        print("[Main] 已停止")


async def main():
    app = RealtimeTranslator()

    # 处理 Ctrl+C 信号
    loop = asyncio.get_running_loop()

    def _signal_handler():
        asyncio.ensure_future(app.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
