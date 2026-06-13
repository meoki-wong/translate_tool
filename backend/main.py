"""
后端主入口 - 流式音频识别 + 实时翻译 + WebSocket 推送

核心设计（投机翻译）:
- vosk partial 实时推送英文到前端（逐词更新）
- partial 文本达到阈值词数时，提前发起"投机翻译"并推送中文
- vosk final 累积到句子缓冲区
- 句子完成后（超时 / 词数阈值）提交：
  - 若投机翻译已覆盖大部分文本 → 直接复用（零延迟）
  - 否则快速翻译最终文本
"""
import asyncio
import signal
import time
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


def _word_prefix_coverage(prefix: str, full: str) -> float:
    """判定 prefix 是否为 full 的词级前缀。

    是前缀返回 len(prefix_words)/len(full_words)（在 [0, 1] 区间），
    否则返回 0.0。不区分大小写。
    """
    pw = prefix.lower().split()
    fw = full.lower().split()
    if not pw or not fw or len(pw) > len(fw):
        return 0.0
    for i, w in enumerate(pw):
        if w != fw[i]:
            return 0.0
    return len(pw) / len(fw)


class RealtimeTranslator:
    """流式实时翻译主控制器（投机翻译架构）

    数据流:
    ┌─────────┐  partial   ┌──────────┐  英文实时  ┌────────┐
    │  vosk   │ ─────────→ │ 主循环    │ ────────→ │ 前端    │
    │  ASR    │            │          │           │ 英文区  │
    └─────────┘            │ 投机翻译  │  中文实时  │        │
                           │ (提前发起) │ ────────→ │ 中文区  │
                           │          │           └────────┘
                           │ 句子缓冲  │
                           │ final累积 │  提交时复用
                           └──────────┘  或快速翻译

    句子提交条件（任一满足）:
    1. 累积词数 >= COMMIT_WORD_COUNT
    2. 静默超时 >= SENTENCE_COMMIT_TIMEOUT
    """

    def __init__(self):
        self.recognizer = StreamRecognizer()
        self.translator = TranslatorManager()
        self.ws_server = WSServer()
        self._running = False

        # 结果队列（线程安全：audio callback → asyncio loop）
        self._result_queue: asyncio.Queue = asyncio.Queue()

        # ── 句子缓冲区 ──
        self._sentence_buffer = ""     # 当前句子英文累积（由 final 拼接）
        self._last_text_time = 0       # 最后一次收到文字的时间
        self._last_partial = ""        # 上次推送的 partial（避免重复推送）
        self._last_committed = ""      # 上次提交的文本（防止重复提交）
        self._committed_segments = []  # 当前 utterance 内已提交的所有片段（用于多轮剥离）
        self._commit_time = 0          # 上次提交时间戳

        # ── 投机翻译状态（序号 + 有限并发）──
        self._speculative_zh = ""          # 最新采纳的投机翻译中文
        self._speculative_en = ""          # 最新采纳的投机翻译对应的英文
        self._speculative_seq = 0          # 单调递增请求序号
        self._speculative_latest_seq = -1  # 已采纳的最大序号（过期结果被丢弃）
        self._inflight_tasks: set = set()  # 在飞的投机翻译任务集合
        self._last_speculative_time = 0    # 上次投机翻译发起时间

        # ── 主循环辅助 ──
        self._stash = None             # 折叠 partial 时临时暂存的非-partial 项

        # ── 翻译锁 ──
        self._translating = False      # 是否正在提交翻译（防止并发）
        self._rate_limited_until = 0   # 被限流直到该时间戳

        # ── 上下文 ──
        self._context_zh = ""          # 最近几句中文（提升翻译连贯性）

    def _on_asr_result(self, result_type: str, text: str):
        """vosk 结果回调（在 sounddevice 音频线程中调用）"""
        try:
            self._result_queue.put_nowait((result_type, text))
        except asyncio.QueueFull:
            pass  # 队列满则丢弃

    def _strip_committed(self, text: str) -> str:
        """从 text 中循环剥离所有已提交片段。

        vosk 在同一 utterance 内不 reset，partial 会包含所有已提交内容。
        需要循环剥离 _committed_segments 中的每个片段（前缀或子串匹配），
        而非只剥离最近一次。

        仅在距上次提交 < 5s 内启用，避免误剥离正常重复表达。
        """
        if not self._committed_segments or not text:
            return text
        if time.time() - self._commit_time > 5.0:
            # 超时清空已提交片段列表，避免跨 utterance 误剥离
            self._committed_segments.clear()
            return text

        changed = True
        while changed:
            changed = False
            tw = text.split()
            if not tw:
                break
            twl = [w.lower() for w in tw]
            for seg in self._committed_segments:
                cw = seg.lower().split()
                if not cw or len(tw) < len(cw):
                    continue
                n = len(cw)
                # 前缀匹配
                if twl[:n] == cw:
                    tw = tw[n:]
                    twl = twl[n:]
                    text = " ".join(tw)
                    changed = True
                    break
                # 子串匹配（取首次出现）
                for i in range(len(twl) - n + 1):
                    if twl[i:i + n] == cw:
                        tw = tw[i + n:]
                        twl = twl[i + n:]
                        text = " ".join(tw)
                        changed = True
                        break
                if changed:
                    break
        return text

    async def _process_loop(self):
        """主处理循环：消费流式识别结果"""
        print("[Main] 流式处理循环已启动")

        while self._running:
            # 优先消费上一轮折叠时暂存的非-partial 项
            if self._stash is not None:
                result_type, text = self._stash
                self._stash = None
            else:
                try:
                    result_type, text = await asyncio.wait_for(
                        self._result_queue.get(), timeout=0.2
                    )
                except asyncio.TimeoutError:
                    # 无新数据 - 检查是否需要提交当前句
                    await self._check_sentence_commit()
                    continue

            # 折叠 partial：队列中如果还有 partial，丢弃中间的只保留最新一个
            # （vosk partial 是当前 utterance 的完整假设，丢中间不丢信息）
            # 遇到 final 等非-partial 项则停止折叠，存入 stash 下轮优先处理
            if result_type == "partial":
                while True:
                    try:
                        peek_type, peek_text = self._result_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if peek_type == "partial":
                        text = peek_text  # 升级为更新的 partial
                        continue
                    else:
                        self._stash = (peek_type, peek_text)
                        break

            now = time.time()

            if result_type == "partial":
                self._last_text_time = now

                # 剥离已提交词序列（防 vosk 累积 / 重叠）
                text = self._strip_committed(text)
                if not text:
                    continue

                # 防止重复提交：刚提交过的相同文本不再触发
                if text == self._last_committed:
                    continue

                # partial 是 vosk 当前 utterance 的完整假设文本
                # 直接推送给前端显示（英文实时更新）
                if text != self._last_partial:
                    self._last_partial = text
                    await self.ws_server.broadcast_partial(
                        text, self._speculative_zh
                    )

                # ★ 核心：partial 词数达到阈值时强制提交，防止无限累积
                partial_words = len(text.split())
                if (partial_words >= config.PARTIAL_COMMIT_THRESHOLD
                        and (now - self._commit_time) > 0.5):  # 提交后冷却 0.5s
                    print(f"[Main] partial 达到 {partial_words} 词，强制提交")
                    # partial 是当前 utterance 的完整假设（含之前 final 已累积的词），
                    # 直接替换 sentence_buffer，不拼接，避免重复
                    self._sentence_buffer = text
                    await self._commit_sentence()
                    continue

                # 投机翻译：partial 词数达到阈值时提前翻译
                # 不再取消旧任务，改为有限并发 + 序号丢弃过期结果
                _max_inflight = config.SPECULATIVE_MAX_INFLIGHT
                _inflight_ok = (
                    _max_inflight <= 0
                    or len(self._inflight_tasks) < _max_inflight
                )
                if (partial_words >= config.SPECULATIVE_WORD_COUNT
                        and now > self._rate_limited_until
                        and (now - self._last_speculative_time) > config.SPECULATIVE_INTERVAL
                        and _inflight_ok
                        and text != self._speculative_en):
                    self._last_speculative_time = now
                    self._speculative_seq += 1
                    seq = self._speculative_seq
                    task = asyncio.create_task(
                        self._speculative_translate(text, seq)
                    )
                    self._inflight_tasks.add(task)
                    task.add_done_callback(self._inflight_tasks.discard)

            elif result_type == "final":
                self._last_text_time = now

                # 剥离已提交词序列（防 vosk 重叠 final / partial 强制提交后残留）
                text = self._strip_committed(text)
                if not text:
                    continue

                # final 是 vosk 完成的一个片段，追加到句子缓冲区
                if self._sentence_buffer:
                    self._sentence_buffer += " " + text
                else:
                    self._sentence_buffer = text

                # 重置 partial 追踪
                self._last_partial = ""

                # 推送更新后的累积文本 + 已有投机翻译
                await self.ws_server.broadcast_partial(
                    self._sentence_buffer, self._speculative_zh
                )

                # 判断是否提交句子
                word_count = len(self._sentence_buffer.split())
                if word_count >= config.COMMIT_WORD_COUNT:
                    await self._commit_sentence()

        print("[Main] 处理循环结束")

    async def _speculative_translate(self, text: str, seq: int):
        """投机翻译：在句子尚未完成时提前翻译 partial 文本。

        多任务并发时靠序号 seq 挑选最新结果，过期的直接丢弃。
        推送条件放宽为词级前缀匹配：只要 text 仍是当前 partial 或
        句子缓冲的词级前缀，结果仍然有效。
        """
        try:
            zh = await self.translator.translate(text, self._context_zh)
            # 丢弃过期结果（后续发起的任务已返回）
            if seq < self._speculative_latest_seq:
                return
            # 词级前缀匹配才采纳，防止不一致翻译覆盖
            current_full = self._sentence_buffer or self._last_partial
            if not current_full:
                return
            if _word_prefix_coverage(text, current_full) <= 0:
                return
            self._speculative_latest_seq = seq
            self._speculative_zh = zh
            self._speculative_en = text
            # 错配保护：task text 较 current_full 落后过多时，
            # 仅保留状态供 commit 复用，不主动推送 UI，
            # 避免出现“老中文 + 新英文”的视觉错配。
            if len(current_full.split()) - len(text.split()) > 3:
                return
            await self.ws_server.broadcast_partial(current_full, zh)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "Too Many" in err_str:
                self._rate_limited_until = time.time() + 30
                print(f"[Main] 投机翻译被限流，暂停 30s")
            # 其他错误静默忽略，不影响主流程

    async def _check_sentence_commit(self):
        """检查是否需要提交当前句子（超时提交）"""
        if not self._sentence_buffer:
            return

        now = time.time()
        if (now - self._last_text_time) > config.SENTENCE_COMMIT_TIMEOUT:
            await self._commit_sentence()

    async def _commit_sentence(self):
        """提交当前句子：复用投机翻译 或 快速翻译 → 推送 → 重置"""
        text = self._sentence_buffer.strip()
        if not text:
            return

        # 防止并发翻译
        if self._translating:
            return

        print(f"[Main] 提交句子 ({len(text.split())} 词): {text}")

        # 不再 cancel 在飞的投机翻译，让其自然结束，并通过推高 latest_seq 使结果作废

        zh_text = ""

        # 尝试复用投机翻译结果（词级前缀判定）
        if self._speculative_zh and self._speculative_en:
            coverage = _word_prefix_coverage(self._speculative_en, text)
            if coverage >= config.SPECULATIVE_REUSE_RATIO:
                zh_text = self._speculative_zh
                print(f"[Main] 复用投机翻译 (词级覆盖率: {coverage:.0%}): {zh_text}")

        # 未能复用 → 快速翻译最终文本
        if not zh_text and time.time() > self._rate_limited_until:
            self._translating = True
            try:
                zh_text = await self.translator.translate(text, self._context_zh)
                print(f"[Main] 翻译结果: {zh_text}")
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "Too Many" in err_str:
                    self._rate_limited_until = time.time() + 30
                    print(f"[Main] 翻译服务被限流，暂停 30s")
                else:
                    print(f"[Main] 翻译失败: {e}")
                zh_text = ""
            finally:
                self._translating = False

        # 更新中文上下文（保留最近 3 句）
        if zh_text:
            if self._context_zh:
                parts = self._context_zh.split("。")[-3:]
                self._context_zh = "。".join(parts)
            self._context_zh += zh_text + "。"

        # 推送已提交字幕到前端（final=True）
        await self.ws_server.broadcast(text, zh_text)

        # 重置所有句子状态
        # 注意：不调用 recognizer.reset()！
        # vosk 在产生 Result() 时已自动重置，手动 Reset 会导致
        # 音频回调中的 AcceptWaveform 崩溃
        # 我们只清除自己的文本缓冲区，vosk 的 partial 会自然刷新
        self._last_committed = self._sentence_buffer.strip()
        self._commit_time = time.time()
        # 记录已提交片段用于后续 partial 多轮剥离
        if self._last_committed:
            self._committed_segments.append(self._last_committed)
        self._sentence_buffer = ""
        self._last_partial = ""
        self._speculative_zh = ""
        self._speculative_en = ""
        # 抢高 latest_seq，使提交前未返回的投机翻译作废、不再覆盖 UI
        self._speculative_latest_seq = self._speculative_seq

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
        import platform as _plat
        print("=" * 50)
        print(f"  实时音频翻译工具 (流式) [{_plat.system()}]")
        print(f"  翻译厂商: {config.TRANSLATOR_PROVIDER}")
        print(f"  ASR 引擎: vosk (流式)")
        print(f"  音频捕获: {self.recognizer.platform_info}")
        print(f"  投机翻译: {config.SPECULATIVE_WORD_COUNT}词触发, "
              f"超时 {config.SENTENCE_COMMIT_TIMEOUT}s, "
              f"提交 {config.COMMIT_WORD_COUNT}词")
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
        # 取消所有在飞的投机翻译任务
        for task in list(self._inflight_tasks):
            if not task.done():
                task.cancel()
        if self._inflight_tasks:
            await asyncio.gather(*self._inflight_tasks, return_exceptions=True)
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
