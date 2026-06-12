#!/bin/bash
# BlackHole 虚拟声卡安装引导脚本

echo "====================================="
echo "  BlackHole 2ch 安装引导"
echo "====================================="
echo ""

# 检查是否已安装
if system_profiler SPAudioDataType 2>/dev/null | grep -q "BlackHole"; then
    echo "✓ BlackHole 已安装！"
else
    echo "BlackHole 未安装。"
    echo ""
    echo "安装方式 1 (推荐 - Homebrew):"
    echo "  brew install blackhole-2ch"
    echo ""
    echo "安装方式 2 (手动下载):"
    echo "  访问 https://existential.audio/blackhole/"
    echo ""

    read -p "是否使用 Homebrew 安装? (y/n): " answer
    if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
        echo "正在安装 BlackHole 2ch..."
        brew install blackhole-2ch
    else
        echo "请手动安装后重新运行此脚本。"
        exit 0
    fi
fi

echo ""
echo "====================================="
echo "  配置多输出音频设备"
echo "====================================="
echo ""
echo "请按以下步骤操作："
echo ""
echo "1. 打开 '音频 MIDI 设置' (Spotlight 搜索 'Audio MIDI Setup')"
echo "2. 点击左下角 '+' 按钮，选择 '创建多输出设备'"
echo "3. 勾选以下设备："
echo "   - BlackHole 2ch"
echo "   - 你的物理扬声器/耳机"
echo "4. 将物理扬声器设为主设备（右键 -> 使用此设备作为声音输出）"
echo "5. 在 '系统设置 -> 声音 -> 输出' 中选择刚创建的 '多输出设备'"
echo ""
echo "配置完成后，应用就能从 BlackHole 捕获音频，同时你仍能听到声音。"
echo ""
echo "✓ 安装引导完成！"
