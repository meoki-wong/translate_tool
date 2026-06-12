"""
音频捕获模块 - 从 BlackHole 虚拟声卡捕获系统音频
"""
import threading
import queue
import numpy as np
import sounddevice as sd
import config


class AudioCapture:
    """从 BlackHole 虚拟声卡捕获音频，基于 VAD 分段后放入队列"""

    def __init__(self):
        self.audio_queue: queue.Queue = queue.Queue(maxsize=100)
        self._running = False
        self._thread = None
        self._device_index = None

        # VAD 状态
        self._buffer = []          # 当前累积的音频块
        self._silence_count = 0    # 连续静音块计数
        self._speech_count = 0     # 连续语音块计数

    def find_blackhole_device(self) -> int | None:
        """查找 BlackHole 虚拟声卡输入设备"""
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            if (config.BLACKHOLE_DEVICE_NAME.lower() in dev['name'].lower()
                    and dev['max_input_channels'] > 0):
                print(f"[AudioCapture] 找到 BlackHole 设备: [{i}] {dev['name']}")
                self._device_index = i
                return i

        print("[AudioCapture] 未找到 BlackHole 设备，可用输入设备:")
        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                print(f"  [{i}] {dev['name']} (输入通道: {dev['max_input_channels']})")
        return None

    def _compute_energy(self, audio_data: np.ndarray) -> float:
        """计算音频块的能量（RMS）"""
        return float(np.sqrt(np.mean(audio_data.astype(np.float64) ** 2)))

    def _on_audio_block(self, indata: np.ndarray, frames: int,
                        time_info, status):
        """音频回调函数 - 每个音频块触发"""
        if status:
            print(f"[AudioCapture] 音频状态: {status}")

        # 转为单声道 int16
        audio = indata[:, 0].copy() if indata.ndim > 1 else indata.flatten().copy()
        energy = self._compute_energy(audio)

        is_speech = energy > config.VAD_ENERGY_THRESHOLD
        silence_frames_threshold = int(
            config.VAD_SILENCE_DURATION / config.BLOCK_DURATION
        )
        min_blocks = int(config.MIN_SEGMENT_DURATION / config.BLOCK_DURATION)
        max_blocks = int(config.MAX_SEGMENT_DURATION / config.BLOCK_DURATION)

        self._buffer.append(audio)

        if is_speech:
            self._speech_count += 1
            self._silence_count = 0
        else:
            self._silence_count += 1

        # 分段条件：检测到足够长的静音，且当前段足够长
        buffer_len = len(self._buffer)
        if (self._silence_count >= silence_frames_threshold
                and buffer_len >= min_blocks
                and self._speech_count > 0):
            self._emit_segment()

        # 强制分段：超过最大时长
        elif buffer_len >= max_blocks and self._speech_count > 0:
            self._emit_segment()

    def _emit_segment(self):
        """将缓冲区音频段放入队列"""
        if not self._buffer:
            return

        segment = np.concatenate(self._buffer)
        duration = len(segment) / config.SAMPLE_RATE

        try:
            self.audio_queue.put_nowait((segment, duration))
        except queue.Full:
            print("[AudioCapture] 队列已满，丢弃音频段")

        self._buffer = []
        self._silence_count = 0
        self._speech_count = 0

    def start(self):
        """启动音频捕获"""
        if self._running:
            return

        if self._device_index is None:
            self.find_blackhole_device()

        if self._device_index is None:
            raise RuntimeError(
                "未找到 BlackHole 虚拟声卡。请先安装 BlackHole 2ch 并配置多输出设备。\n"
                "安装命令: brew install blackhole-2ch"
            )

        block_size = int(config.SAMPLE_RATE * config.BLOCK_DURATION)
        self._running = True

        self._stream = sd.InputStream(
            device=self._device_index,
            samplerate=config.SAMPLE_RATE,
            channels=config.CHANNELS,
            dtype='int16',
            blocksize=block_size,
            callback=self._on_audio_block,
        )
        self._stream.start()
        print(f"[AudioCapture] 音频捕获已启动 (设备: {self._device_index}, "
              f"采样率: {config.SAMPLE_RATE}Hz)")

    def stop(self):
        """停止音频捕获"""
        self._running = False
        if hasattr(self, '_stream'):
            self._stream.stop()
            self._stream.close()
        print("[AudioCapture] 音频捕获已停止")

    def get_segment(self, timeout=5.0):
        """从队列获取一个音频段（阻塞）"""
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None
