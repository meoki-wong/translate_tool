"""
流式语音识别模块 - 基于 vosk 的实时流式 ASR
逐词输出识别结果，替代 faster-whisper 的段落式识别
"""
import json
import queue
import threading
import os
from pathlib import Path

import numpy as np
import sounddevice as sd
from vosk import Model, KaldiRecognizer

import config


class StreamRecognizer:
    """基于 vosk 的流式语音识别器
    
    直接从音频设备捕获音频并实时识别，
    通过回调函数推送 partial（中间结果）和 final（最终结果）。
    """

    def __init__(self):
        self._model = None
        self._recognizer = None
        self._stream = None
        self._running = False
        self._device_index = None
        self._on_result = None  # callback(result_type: str, text: str)

    def set_result_callback(self, callback):
        """设置结果回调函数
        
        callback 签名: callback(result_type: str, text: str)
            result_type: "partial" 或 "final"
            text: 识别文本
        """
        self._on_result = callback

    def load_model(self):
        """加载 vosk 模型"""
        model_path = Path(config.VOSK_MODEL_PATH)

        if not model_path.exists():
            raise RuntimeError(
                f"vosk 模型不存在: {model_path}\n"
                f"请手动下载: https://alphacephei.com/vosk/models\n"
                f"推荐: vosk-model-small-en-us-0.15 (约 50MB)"
            )

        print(f"[StreamRecognizer] 加载 vosk 模型: {model_path}")
        self._model = Model(str(model_path))
        self._recognizer = KaldiRecognizer(self._model, config.SAMPLE_RATE)
        self._recognizer.SetWords(True)
        print("[StreamRecognizer] 模型加载完成")

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def find_device(self) -> int | None:
        """查找 BlackHole 虚拟声卡输入设备"""
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            if (config.BLACKHOLE_DEVICE_NAME.lower() in dev['name'].lower()
                    and dev['max_input_channels'] > 0):
                print(f"[StreamRecognizer] 找到设备: [{i}] {dev['name']}")
                self._device_index = i
                return i

        print("[StreamRecognizer] 未找到 BlackHole，可用输入设备:")
        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                print(f"  [{i}] {dev['name']} (ch: {dev['max_input_channels']})")
        return None

    def _audio_callback(self, indata: np.ndarray, frames: int,
                        time_info, status):
        """音频回调 - 每个音频块直接送入 vosk 识别"""
        if status:
            print(f"[StreamRecognizer] 音频状态: {status}")

        if not self._running or not self._recognizer:
            return

        # 转单声道 int16 字节
        if indata.ndim > 1:
            audio_bytes = indata[:, 0].tobytes()
        else:
            audio_bytes = indata.tobytes()

        # 送入 vosk 识别
        # AcceptWaveform 返回 int: 1=有最终结果, 0=还在识别中
        is_final = self._recognizer.AcceptWaveform(audio_bytes)

        if self._on_result:
            if is_final:
                # 最终结果（一句话结束）
                data = json.loads(self._recognizer.Result())
                text = data.get("text", "").strip()
                if text:
                    self._on_result("final", text)
            else:
                # 中间结果（实时更新）
                data = json.loads(self._recognizer.PartialResult())
                text = data.get("partial", "").strip()
                if text:
                    self._on_result("partial", text)

    def start(self):
        """启动流式识别（含音频捕获）"""
        if self._running:
            return

        if not self.loaded:
            self.load_model()

        if self._device_index is None:
            self.find_device()

        if self._device_index is None:
            raise RuntimeError(
                "未找到 BlackHole 虚拟声卡。\n"
                "请先安装: brew install blackhole-2ch\n"
                "然后配置多输出设备。"
            )

        block_size = int(config.SAMPLE_RATE * config.BLOCK_DURATION)
        self._running = True

        self._stream = sd.InputStream(
            device=self._device_index,
            samplerate=config.SAMPLE_RATE,
            channels=config.CHANNELS,
            dtype='int16',
            blocksize=block_size,
            callback=self._audio_callback,
        )
        self._stream.start()
        print(f"[StreamRecognizer] 流式识别已启动 "
              f"(设备: {self._device_index}, "
              f"采样率: {config.SAMPLE_RATE}Hz, "
              f"块大小: {block_size})")

    def stop(self):
        """停止流式识别"""
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        print("[StreamRecognizer] 流式识别已停止")

    def reset(self):
        """重置识别器状态（切换句子时调用）"""
        if self._recognizer:
            # vosk 的 Reset 会清除内部状态
            self._recognizer.Reset()
