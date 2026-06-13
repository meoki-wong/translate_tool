"""
Windows 音频捕获 - WASAPI 回环

Windows 原生支持 WASAPI 回环捕获，无需安装虚拟声卡。
直接捕获系统正在播放的音频（扬声器/耳机输出）。

使用 sounddevice 的 WASAPI 回环特性：
- extra_settings = sd.WasapiSettings(loopback=True)
- 设备使用默认输出设备（扬声器），但读回环数据
"""
import sounddevice as sd

# 找不到设备时的提示信息
INSTALL_HINT = (
    "未找到可用的音频输出设备。\n"
    "请确保系统有可用的扬声器或耳机。"
)


def find_device() -> int | None:
    """查找 WASAPI 回环设备（默认输出设备）
    
    Windows 上 WASAPI 回环捕获使用默认输出设备（扬声器/耳机），
    不需要安装任何虚拟声卡。
    
    Returns:
        设备索引，未找到返回 None
    """
    try:
        # 获取默认输出设备（WASAPI 回环从输出设备读音频）
        device_index = sd.default.device[1]  # [输入, 输出] → 取输出
        if device_index is not None:
            dev = sd.query_devices(device_index)
            print(f"[WinAudio] 使用 WASAPI 回环设备: [{device_index}] {dev['name']}")
            return device_index
    except Exception:
        pass

    # 降级：查找任何输出设备
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        if dev['max_output_channels'] > 0 and 'wasapi' in str(dev).lower():
            print(f"[WinAudio] 找到 WASAPI 输出设备: [{i}] {dev['name']}")
            return i

    # 再降级：任意有输出通道的设备
    for i, dev in enumerate(devices):
        if dev['max_output_channels'] > 0:
            print(f"[WinAudio] 找到输出设备: [{i}] {dev['name']}")
            return i

    print("[WinAudio] 未找到可用的音频输出设备")
    return None


def get_device_info(device_index: int) -> dict:
    """获取设备信息"""
    dev = sd.query_devices(device_index)
    return {
        "name": dev['name'],
        "channels": dev['max_output_channels'],
        "sample_rate": int(dev['default_samplerate']),
        "platform": "Windows",
        "method": "WASAPI Loopback",
    }


def get_stream_params(device_index: int, sample_rate: int,
                      channels: int, block_duration: float) -> dict:
    """获取 InputStream 启动参数（WASAPI 回环模式）
    
    关键区别：
    - 使用 WasapiSettings(loopback=True) 开启回环捕获
    - channels 取设备实际输出通道数（通常是 2 = 立体声）
    - 回环模式下读取的是系统正在播放的音频
    
    Returns:
        可直接传给 sd.InputStream(**params) 的字典
    """
    block_size = int(sample_rate * block_duration)

    # WASAPI 回环设置
    wasapi_settings = sd.WasapiSettings(loopback=True)

    # 回环模式使用设备原始输出通道数（通常立体声 = 2）
    dev = sd.query_devices(device_index)
    actual_channels = dev['max_output_channels']

    return {
        "device": device_index,
        "samplerate": sample_rate,
        "channels": actual_channels,
        "dtype": "int16",
        "blocksize": block_size,
        "extra_settings": wasapi_settings,
    }
