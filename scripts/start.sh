#!/bin/bash
# 一键启动脚本 - 同时启动 Python 后端和 Tauri 前端

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

echo "====================================="
echo "  Mac 实时音频翻译工具"
echo "====================================="
echo ""

# 检查 Python 虚拟环境
if [ ! -d "$BACKEND_DIR/venv" ]; then
    echo "⚠ Python 虚拟环境不存在，正在创建..."
    cd "$BACKEND_DIR"
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    echo "✓ 虚拟环境创建完成"
else
    echo "✓ Python 虚拟环境已就绪"
fi

# 检查前端依赖
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo "⚠ 前端依赖未安装，正在安装..."
    cd "$FRONTEND_DIR"
    npm install
    echo "✓ 前端依赖安装完成"
else
    echo "✓ 前端依赖已就绪"
fi

# 检查翻译 API 配置（同时检查环境变量和 config.py）
CONFIG_FILE="$BACKEND_DIR/config.py"
HAS_KEY=false

# 检查环境变量
if [ -n "$HUNYUAN_SECRET_ID" ] && [ -n "$HUNYUAN_SECRET_KEY" ]; then
    HAS_KEY=true
fi

# 检查 .env 文件
ENV_FILE="$PROJECT_DIR/.env"
if [ "$HAS_KEY" = false ] && [ -f "$ENV_FILE" ]; then
    ENV_ID=$(grep -E '^HUNYUAN_SECRET_ID=' "$ENV_FILE" | cut -d'=' -f2- | tr -d '[:space:]')
    ENV_KEY=$(grep -E '^HUNYUAN_SECRET_KEY=' "$ENV_FILE" | cut -d'=' -f2- | tr -d '[:space:]')
    if [ -n "$ENV_ID" ] && [ -n "$ENV_KEY" ]; then
        echo "✓ 从 .env 文件读取到混元翻译密钥"
        export HUNYUAN_SECRET_ID="$ENV_ID"
        export HUNYUAN_SECRET_KEY="$ENV_KEY"
        HAS_KEY=true
    fi
fi

# 检查 config.py 中是否直接配置了密钥
if [ "$HAS_KEY" = false ] && [ -f "$CONFIG_FILE" ]; then
    PY_ID=$(python3 -c "
import re
with open('$CONFIG_FILE') as f:
    for line in f:
        m = re.match(r'HUNYUAN_SECRET_ID\s*=\s*os\.getenv\([^,]+,\s*[\"\'](.*?)[\"\']\)', line)
        if m and m.group(1):
            print(m.group(1))
            break
" 2>/dev/null)
    PY_KEY=$(python3 -c "
import re
with open('$CONFIG_FILE') as f:
    for line in f:
        m = re.match(r'HUNYUAN_SECRET_KEY\s*=\s*os\.getenv\([^,]+,\s*[\"\'](.*?)[\"\']\)', line)
        if m and m.group(1):
            print(m.group(1))
            break
" 2>/dev/null)
    if [ -n "$PY_ID" ] && [ -n "$PY_KEY" ]; then
        echo "✓ 从 config.py 读取到混元翻译密钥"
        export HUNYUAN_SECRET_ID="$PY_ID"
        export HUNYUAN_SECRET_KEY="$PY_KEY"
        HAS_KEY=true
    fi
fi

# 检查是否使用其他翻译厂商
if [ "$HAS_KEY" = false ] && [ -n "$TRANSLATOR_PROVIDER" ] && [ "$TRANSLATOR_PROVIDER" != "hunyuan" ]; then
    echo "✓ 使用翻译厂商: $TRANSLATOR_PROVIDER"
    HAS_KEY=true
fi

# 检查 config.py 中的 TRANSLATOR_PROVIDER
if [ "$HAS_KEY" = false ] && [ -f "$CONFIG_FILE" ]; then
    PROVIDER=$(python3 -c "
import re
with open('$CONFIG_FILE') as f:
    for line in f:
        m = re.match(r'TRANSLATOR_PROVIDER\s*=\s*os\.getenv\([^,]+,\s*[\"\'](.*?)[\"\']\)', line)
        if m and m.group(1) and m.group(1) != 'hunyuan':
            print(m.group(1))
            break
" 2>/dev/null)
    if [ -n "$PROVIDER" ]; then
        echo "✓ 从 config.py 读取到翻译厂商: $PROVIDER"
        export TRANSLATOR_PROVIDER="$PROVIDER"
        HAS_KEY=true
    fi
fi

if [ "$HAS_KEY" = false ]; then
    echo ""
    echo "⚠ 混元翻译 API 密钥未配置！"
    echo "  配置方式（任选其一）："
    echo ""
    echo "  方式 1 - 环境变量："
    echo "    export HUNYUAN_SECRET_ID=your_id"
    echo "    export HUNYUAN_SECRET_KEY=your_key"
    echo ""
    echo "  方式 2 - 直接编辑 config.py 填入密钥"
    echo ""
    echo "  方式 3 - 使用 MyMemory（无需配置）："
    echo "    export TRANSLATOR_PROVIDER=mymemory"
    echo ""
    read -p "是否使用 MyMemory 继续（无需配置）? (y/n): " answer
    if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
        export TRANSLATOR_PROVIDER=mymemory
    else
        echo "请先配置 API 密钥后重新运行。"
        exit 0
    fi
fi

echo ""
echo "启动方式选择："
echo "  1. 仅启动 Python 后端（调试用）"
echo "  2. 启动完整应用（Tauri + Python）"
echo ""
read -p "请选择 (1/2): " choice

case $choice in
    1)
        echo ""
        echo "正在启动 Python 后端..."
        cd "$BACKEND_DIR"
        source venv/bin/activate
        python main.py
        ;;
    2)
        echo ""
        echo "正在启动 Tauri 应用..."
        cd "$FRONTEND_DIR"
        npm run tauri dev
        ;;
    *)
        echo "无效选择"
        exit 1
        ;;
esac
