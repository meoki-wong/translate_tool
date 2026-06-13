"""
流式语音识别模块 - 基于 vosk 的实时流式 ASR（跨平台）

macOS:  使用 BlackHole 虚拟声卡捕获系统音频
Windows: 使用 WASAPI 回环直接捕获系统音频（无需虚拟声卡）
"""
import json
import platform
from pathlib import Path

import numpy as np
import sounddevice as sd
from vosk import Model, KaldiRecognizer

import config

# 根据平台导入对应音频模块
SYSTEM = platform.system()
if SYSTEM == "Darwin":
    from audio import mac_audio as _audio_provider
elif SYSTEM == "Windows":
    from audio import win_audio as _audio_provider
else:
    _audio_provider = None


class StreamRecognizer:
    """基于 vosk 的流式语音识别器（跨平台）
    
    直接从音频设备捕获音频并实时识别，
    通过回调函数推送 partial（中间结果）和 final（最终结果）。
    
    平台差异:
    - macOS:   BlackHole 虚拟声卡（需额外安装）
    - Windows: WASAPI 回环（原生支持，无需安装）
    """

    def __init__(self):
        self._model = None
        self._recognizer = None
        self._stream = None
        self._running = False
        self._device_index = None
        self._on_result = None  # callback(result_type: str, text: str)
        self._platform = SYSTEM

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

    @property
    def platform_info(self) -> str:
        """当前平台信息"""
        return f"{self._platform} / {_audio_provider.__name__ if _audio_provider else 'unknown'}"

    def find_device(self) -> int | None:
        """查找音频设备（跨平台）
        
        macOS:   查找 BlackHole 虚拟声卡输入设备
        Windows: 查找 WASAPI 回环输出设备
        
        Returns:
            设备索引，未找到返回 None
        """
        if _audio_provider is None:
            print(f"[StreamRecognizer] 不支持的平台: {self._platform}")
            return None

        self._device_index = _audio_provider.find_device()
        return self._device_index

    def _audio_callback(self, indata: np.ndarray, frames: int,
                        time_info, status):
        """音频回调 - 每个音频块直接送入 vosk 识别"""
        if status:
            # 仅在严重错误时打印，xrun（溢出）属于正常现象
            if hasattr(status, 'input_overflow') and status.input_overflow:
                pass  # 忽略常见的溢出警告
            else:
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
            # 使用平台对应的错误提示
            if _audio_provider:
                raise RuntimeError(_audio_provider.INSTALL_HINT)
            raise RuntimeError(
                f"不支持的平台: {self._platform}，仅支持 macOS 和 Windows"
            )

        # 获取平台对应的流参数
        stream_params = _audio_provider.get_stream_params(
            self._device_index,
            config.SAMPLE_RATE,
            config.CHANNELS,
            config.BLOCK_DURATION,
        )

        self._running = True

        # 创建并启动音频流
        self._stream = sd.InputStream(
            callback=self._audio_callback,
            **stream_params,
        )
        self._stream.start()

        # 打印设备信息
        dev_info = _audio_provider.get_device_info(self._device_index)
        print(f"[StreamRecognizer] 流式识别已启动")
        print(f"  平台: {dev_info['platform']} ({dev_info['method']})")
        print(f"  设备: [{self._device_index}] {dev_info['name']}")
        print(f"  采样率: {config.SAMPLE_RATE}Hz, 通道: {config.CHANNELS}")

    def stop(self):
        """停止流式识别"""
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                print(f"[StreamRecognizer] 停止音频流异常: {e}")
            self._stream = None
        print("[StreamRecognizer] 流式识别已停止")

    def reset(self):
        """重置识别器状态（切换句子时调用）"""
        if self._recognizer:
            try:
                self._recognizer.Reset()
            except Exception as e:
                print(f"[StreamRecognizer] 重置异常: {e}")
