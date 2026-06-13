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
import os
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
        self._committed_word_count = 0 # 当前 utterance 内已提交的累积词数（用于截取 partial 尾部）

        # ── 投机翻译状态（序号 + 有限并发）──
        self._speculative_zh = ""          # 最新采纳的投机翻译中文
        self._speculative_en = ""          # 最新采纳的投机翻译对应的英文
        self._speculative_seq = 0          # 单调递增请求序号
        self._speculative_latest_seq = -1  # 已采纳的最大序号（过期结果被丢弃）
        self._inflight_tasks: set = set()  # 在飞的投机翻译任务集合
        self._last_speculative_time = 0    # 上次投机翻译发起时间

        # ── 主循环辅助 ──
        self._stash = None             # 折叠 partial 时临时暂存的非-partial 项
        self._pending_commit = None    # 后台提交 task（非阻塞化）

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
            self._committed_word_count = 0
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

                # 剥离已提交词序列得到增量文本（仅用于内部判断）
                stripped = self._strip_committed(text)

                # 前端推送：截取 partial 中已提交词数之后的尾部
                # 这样 live 区只显示未提交的新内容，不会叠加已提交文字
                all_words = text.split()
                if len(all_words) > self._committed_word_count:
                    display_text = " ".join(all_words[self._committed_word_count:])
                else:
                    display_text = ""

                if display_text and display_text != self._last_partial:
                    self._last_partial = display_text
                    await self.ws_server.broadcast_partial(
                        display_text, self._speculative_zh
                    )
                elif not display_text:
                    # 无新内容可显示，清空 live 区
                    if self._last_partial:
                        self._last_partial = ""
                        await self.ws_server.broadcast_partial("", "")

                # 无增量内容则跳过后续逻辑
                if not stripped or stripped == self._last_committed:
                    continue

                # ★ 核心：增量词数达到阈值时强制提交
                partial_words = len(stripped.split())
                if (partial_words >= config.PARTIAL_COMMIT_THRESHOLD
                        and (now - self._commit_time) > 0.5):  # 提交后冷却 0.5s
                    print(f"[Main] partial 增量达到 {partial_words} 词，强制提交")
                    # sentence_buffer 用增量文本（stripped），不含已提交内容
                    self._sentence_buffer = stripped
                    await self._commit_sentence()
                    continue

                # 投机翻译：基于增量文本判断词数
                _max_inflight = config.SPECULATIVE_MAX_INFLIGHT
                _inflight_ok = (
                    _max_inflight <= 0
                    or len(self._inflight_tasks) < _max_inflight
                )
                if (partial_words >= config.SPECULATIVE_WORD_COUNT
                        and now > self._rate_limited_until
                        and (now - self._last_speculative_time) > config.SPECULATIVE_INTERVAL
                        and _inflight_ok
                        and stripped != self._speculative_en):
                    self._last_speculative_time = now
                    self._speculative_seq += 1
                    seq = self._speculative_seq
                    task = asyncio.create_task(
                        self._speculative_translate(stripped, seq)
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
            # 避免出现"老中文 + 新英文"的视觉错配。
            if len(current_full.split()) - len(text.split()) > 3:
                return
            # 仅在英文文本与 current_full 一致时推送，
            # 避免中文单独跳变导致 UI 闪烁
            if current_full != self._last_partial:
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
        """提交当前句子：复用投机翻译 或 快速翻译 → 推送 → 重置

        翻译阶段不阻塞主循环：若需要调用翻译器，将翻译放入后台 task，
        主循环可继续处理 partial。若复用投机翻译结果则直接推送（零延迟）。
        """
        text = self._sentence_buffer.strip()
        if not text:
            return

        # 防止并发提交
        if self._translating:
            return

        print(f"[Main] 提交句子 ({len(text.split())} 词): {text}")

        zh_text = ""

        # 尝试复用投机翻译结果（词级前缀判定）— 零延迟路径
        if self._speculative_zh and self._speculative_en:
            coverage = _word_prefix_coverage(self._speculative_en, text)
            if coverage >= config.SPECULATIVE_REUSE_RATIO:
                zh_text = self._speculative_zh
                print(f"[Main] 复用投机翻译 (词级覆盖率: {coverage:.0%}): {zh_text}")

        if zh_text:
            # 零延迟：直接推送复用结果
            await self._finalize_commit(text, zh_text)
        elif time.time() > self._rate_limited_until:
            # 需要翻译：非阻塞化，后台 task 执行
            self._translating = True
            # 立即设置 _last_committed 和 _commit_time，让后续 partial 能正确剥离
            self._last_committed = text
            self._commit_time = time.time()
            if self._last_committed:
                self._committed_segments.append(self._last_committed)
                self._committed_word_count += len(text.split())
            # 立即清空 sentence_buffer，让主循环继续接收新 partial
            self._sentence_buffer = ""
            self._last_partial = ""
            self._speculative_zh = ""
            self._speculative_en = ""
            self._speculative_latest_seq = self._speculative_seq
            commit_text = text  # 闭包捕获
            if self._pending_commit and not self._pending_commit.done():
                self._pending_commit.cancel()
            self._pending_commit = asyncio.create_task(
                self._do_commit_translate(commit_text)
            )
        else:
            # 被限流，直接推送无翻译结果
            await self._finalize_commit(text, "")

    async def _do_commit_translate(self, text: str):
        """后台执行提交翻译（不阻塞主循环）"""
        zh_text = ""
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
        finally:
            self._translating = False
        await self._finalize_commit(text, zh_text)

    async def _finalize_commit(self, text: str, zh_text: str):
        """提交收尾：更新上下文 + 推送 + 重置状态"""
        # 更新中文上下文（保留最近 3 句）
        if zh_text:
            if self._context_zh:
                parts = self._context_zh.split("。")[-3:]
                self._context_zh = "。".join(parts)
            self._context_zh += zh_text + "。"

        # 推送已提交字幕到前端（final=True）
        await self.ws_server.broadcast(text, zh_text)

        # 同步路径需要补设 _last_committed；异步路径已在 _commit_sentence 中设置
        if self._last_committed != text:
            self._last_committed = text
            self._commit_time = time.time()
            if self._last_committed:
                self._committed_segments.append(self._last_committed)
                self._committed_word_count += len(text.split())

        # 清除 buffer（仅同步路径需要；异步路径已提前清除）
        if self._sentence_buffer.strip() == text:
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
        elif action == "switch_lang":
            source_lang = data.get("source_lang")
            target_lang = data.get("target_lang")
            changed = False
            if source_lang and source_lang != config.SOURCE_LANG:
                # 检查是否有对应的 vosk 模型
                if source_lang in config.VOSK_MODEL_MAP:
                    config.SOURCE_LANG = source_lang
                    config.VOSK_MODEL_PATH = os.path.join(
                        os.path.dirname(__file__), "models",
                        config.VOSK_MODEL_MAP.get(source_lang, "vosk-model-small-en-us-0.15")
                    )
                    changed = True
                else:
                    src_name = config.LANG_NAMES.get(source_lang, source_lang)
                    await self.ws_server.broadcast_status(
                        "error", f"暂不支持 {src_name} 语音识别（缺少 vosk 模型）"
                    )
                    return
            if target_lang and target_lang != config.TARGET_LANG:
                config.TARGET_LANG = target_lang
                changed = True
            if changed:
                # 重置状态避免残留旧语言内容
                self._sentence_buffer = ""
                self._last_partial = ""
                self._speculative_zh = ""
                self._speculative_en = ""
                self._committed_segments.clear()
                self._committed_word_count = 0
                self._context_zh = ""
                src_name = config.LANG_NAMES.get(config.SOURCE_LANG, config.SOURCE_LANG)
                tgt_name = config.LANG_NAMES.get(config.TARGET_LANG.replace("-CN", ""), config.TARGET_LANG)
                print(f"[Main] 语言已切换: {src_name} → {tgt_name}")
                await self.ws_server.broadcast_status(
                    "lang_changed",
                    f"{src_name} → {tgt_name}"
                )

    async def run(self):
        """启动所有服务"""
        import platform as _plat
        print("=" * 50)
        print(f"  实时音频翻译工具 (流式) [{_plat.system()}]")
        print(f"  翻译厂商: {config.TRANSLATOR_PROVIDER}")
        src_name = config.LANG_NAMES.get(config.SOURCE_LANG, config.SOURCE_LANG)
        tgt_name = config.LANG_NAMES.get(config.TARGET_LANG.replace('-CN', ''), config.TARGET_LANG)
        print(f"  翻译语言: {src_name} → {tgt_name}")
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
        if self._pending_commit and not self._pending_commit.done():
            self._pending_commit.cancel()
        wait_tasks = list(self._inflight_tasks)
        if self._pending_commit and not self._pending_commit.done():
            wait_tasks.append(self._pending_commit)
        if wait_tasks:
            await asyncio.gather(*wait_tasks, return_exceptions=True)
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
