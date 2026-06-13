"""
跨平台音频捕获模块

macOS: BlackHole 虚拟声卡
Windows: WASAPI 回环（无需额外安装）
"""
import platform

SYSTEM = platform.system()


def get_audio_provider():
    """根据当前平台返回对应的音频提供模块"""
    if SYSTEM == "Darwin":
        from . import mac_audio
        return mac_audio
    elif SYSTEM == "Windows":
        from . import win_audio
        return win_audio
    else:
        raise RuntimeError(f"不支持的操作系统: {SYSTEM}，仅支持 macOS 和 Windows")
