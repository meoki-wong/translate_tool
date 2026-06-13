# Mac 实时音频翻译工具

> 基于 Tauri v2 + vosk 流式 ASR + 多翻译厂商的 Mac 桌面实时翻译字幕应用。
> 捕获系统音频（BlackHole 虚拟声卡），实时识别英文语音并翻译为中文，以字幕形式叠加显示。

## 功能特性

- **流式语音识别** — 基于 [vosk](https://alphacephei.com/vosk/) 逐词实时识别，延迟约 0.5-1s
- **多翻译厂商** — 支持 6 种翻译后端，运行时一键切换：
  | 厂商 | 说明 | 免费 |
  |------|------|------|
  | MyMemory | 无需配置，开箱即用 | ✅ 5000 字符/天 |
  | Ollama | 本地大模型，无需联网 | ✅ |
  | 混元翻译 | 腾讯大模型，质量高 | ❌ |
  | DeepL | 高质量机器翻译 | ❌ |
  | 百度翻译 | 国内常用 | ❌ |
  | OpenAI | GPT 翻译 | ❌ |
- **字幕叠加** — 透明背景窗口，可调节字体大小、透明度
- **窗口置顶** — 一键切换窗口置顶，始终显示在最上层
- **设置弹窗** — 运行时切换翻译厂商，无需重启

## 系统要求

- macOS 12+
- Rust 1.85+（Tauri v2）
- Python 3.11+
- Node.js 18+
- [BlackHole 2ch](https://existential.audio/blackhole/)（虚拟声卡）

## 快速开始

### 1. 安装 BlackHole

```bash
brew install blackhole-2ch
```

安装后需在 **音频 MIDI 设置**（`/System/Applications/Utilities/Audio MIDI Setup.app`）中：
1. 点击左下角 `+` → 创建 **多输出设备**
2. 勾选你的 **物理扬声器/耳机** + **BlackHole 2ch**
3. 在系统设置 → 声音 → 输出中选择该多输出设备

### 2. 克隆并启动

```bash
git clone <repo-url>
cd test_translate_tool
bash scripts/start.sh
```

启动脚本会自动：
- 创建 Python 虚拟环境并安装依赖
- 下载 vosk 语音识别模型（首次约 50MB）
- 安装前端依赖
- 启动 Tauri 应用

### 3. 配置翻译密钥（可选）

默认使用免费的 MyMemory，无需配置。如需使用其他厂商：

```bash
# 方式 1：创建 .env 文件
cat > .env << EOF
TRANSLATOR_PROVIDER=hunyuan
HUNYUAN_SECRET_ID=your_id
HUNYUAN_SECRET_KEY=your_key
EOF

# 方式 2：环境变量
export TRANSLATOR_PROVIDER=ollama
export OLLAMA_BASE_URL=http://localhost:11434
export OLLAMA_MODEL=qwen2:7b-instruct
```

## 项目结构

```
test_translate_tool/
├── backend/                    # Python 后端
│   ├── main.py                 # 主入口：流式处理循环
│   ├── stream_recognizer.py    # vosk 流式语音识别
│   ├── translator.py           # 多厂商翻译器（策略模式）
│   ├── ws_server.py            # WebSocket 服务端
│   ├── config.py               # 全局配置
│   ├── requirements.txt        # Python 依赖
│   └── models/                 # vosk 模型（不入 git）
├── frontend/                   # Tauri 前端
│   ├── src/
│   │   ├── App.tsx             # 主界面：字幕显示 + 设置弹窗
│   │   └── App.css             # 样式
│   └── src-tauri/
│       ├── src/lib.rs          # Rust 后端：窗口控制、Python 启动
│       └── tauri.conf.json     # Tauri 配置
├── scripts/
│   └── start.sh                # 一键启动脚本
├── .env                        # 本地环境变量（不入 git）
└── .gitignore
```

## 架构

```
BlackHole 音频 → sounddevice 回调 → vosk 流式识别
                                          ↓
                              partial（逐词更新）→ WebSocket → 前端 LIVE 字幕
                              final（句子结束）→ 累积 → 翻译 → WebSocket → 历史字幕
```

- **vosk** 在音频回调中实时处理每个 0.1s 的音频块
- **partial 结果** 立即推送前端，更新 LIVE 区域
- **final 结果** 累积文本，1.5s 无新内容后提交句子并翻译
- **WebSocket** 双向通信，支持运行时切换翻译厂商

## 开发

```bash
# 仅启动后端（调试用）
cd backend && source venv/bin/activate && python main.py

# 启动前端（Vite 热更新）
cd frontend && npm run dev

# 完整应用
bash scripts/start.sh
```

## 许可证

MIT
