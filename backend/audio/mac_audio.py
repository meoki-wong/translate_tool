"""
macOS 音频捕获 - BlackHole 虚拟声卡

需要预先安装: brew install blackhole-2ch
并创建多输出设备（物理扬声器 + BlackHole）
"""
import sounddevice as sd

# BlackHole 设备名称关键词
DEVICE_KEYWORD = "BlackHole"

# 找不到设备时的提示信息
INSTALL_HINT = (
    "未找到 BlackHole 虚拟声卡。\n"
    "请先安装: brew install blackhole-2ch\n"
    "然后重启 CoreAudio: sudo killall coreaudiod\n"
    "最后在 Audio MIDI Setup 中创建多输出设备。"
)


def find_device() -> int | None:
    """查找 BlackHole 虚拟声卡输入设备
    
    Returns:
        设备索引，未找到返回 None
    """
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        if (DEVICE_KEYWORD.lower() in dev['name'].lower()
                and dev['max_input_channels'] > 0):
            print(f"[MacAudio] 找到 BlackHole 设备: [{i}] {dev['name']}")
            return i

    print("[MacAudio] 未找到 BlackHole，可用输入设备:")
    for i, dev in enumerate(devices):
        if dev['max_input_channels'] > 0:
            print(f"  [{i}] {dev['name']} (ch: {dev['max_input_channels']})")
    return None


def get_device_info(device_index: int) -> dict:
    """获取设备信息"""
    dev = sd.query_devices(device_index)
    return {
        "name": dev['name'],
        "channels": dev['max_input_channels'],
        "sample_rate": int(dev['default_samplerate']),
        "platform": "macOS",
        "method": "BlackHole",
    }


def get_stream_params(device_index: int, sample_rate: int,
                      channels: int, block_duration: float) -> dict:
    """获取 InputStream 启动参数
    
    Returns:
        可直接传给 sd.InputStream(**params) 的字典
    """
    block_size = int(sample_rate * block_duration)
    return {
        "device": device_index,
        "samplerate": sample_rate,
        "channels": channels,
        "dtype": "int16",
        "blocksize": block_size,
    }
