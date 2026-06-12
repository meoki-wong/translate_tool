"""
语音识别模块 - 使用 faster-whisper 进行本地英文语音识别
"""
import numpy as np
from faster_whisper import WhisperModel
import config


class SpeechRecognizer:
    """基于 faster-whisper 的本地语音识别器"""

    def __init__(self):
        self._model = None
        self._context_prompt = ""  # 滑动窗口上下文

    def load_model(self):
        """加载 Whisper 模型"""
        print(f"[SpeechRecognizer] 正在加载 Whisper 模型 ({config.WHISPER_MODEL_SIZE})...")
        device = config.WHISPER_DEVICE
        if device == "auto":
            device = "cpu"

        self._model = WhisperModel(
            config.WHISPER_MODEL_SIZE,
            device=device,
            compute_type=config.WHISPER_COMPUTE_TYPE,
        )
        print("[SpeechRecognizer] 模型加载完成")

    def transcribe(self, audio_segment: np.ndarray, duration: float) -> dict:
        """
        识别音频段

        Args:
            audio_segment: int16 numpy 数组
            duration: 音频段时长（秒）

        Returns:
            dict: {"text": str, "segments": list, "duration": float}
        """
        if self._model is None:
            self.load_model()

        # faster-whisper 需要 float32 归一化音频
        audio_float = audio_segment.astype(np.float32) / 32768.0

        segments, info = self._model.transcribe(
            audio_float,
            language=config.WHISPER_LANGUAGE,
            initial_prompt=self._context_prompt if self._context_prompt else None,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=300,
                speech_pad_ms=200,
            ),
        )

        # 收集所有识别结果
        result_segments = []
        full_text_parts = []
        for seg in segments:
            result_segments.append({
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
            })
            full_text_parts.append(seg.text.strip())

        full_text = " ".join(full_text_parts).strip()

        # 更新滑动窗口上下文（保留最后 3 句）
        if result_segments:
            last_texts = [s["text"] for s in result_segments[-3:]]
            self._context_prompt = " ".join(last_texts)

        return {
            "text": full_text,
            "segments": result_segments,
            "duration": duration,
        }
