# Wiki - Mac 实时音频翻译工具

## 目录

1. [BlackHole 音频配置指南](#blackhole-音频配置指南)
2. [翻译厂商接入指南](#翻译厂商接入指南)
3. [流式识别架构详解](#流式识别架构详解)
4. [前端交互说明](#前端交互说明)
5. [常见问题排查](#常见问题排查)
6. [配置参考](#配置参考)

---

## BlackHole 音频配置指南

### 原理

应用通过 **BlackHole 2ch** 虚拟声卡捕获系统音频。但直接使用 BlackHole 会导致耳机没声音，因此需要创建 **多输出设备**（物理扬声器 + BlackHole）。

### 配置步骤

1. **安装 BlackHole**
   ```bash
   brew install blackhole-2ch
   ```

2. **重启 CoreAudio**（安装后必须）
   ```bash
   sudo killall coreaudiod
   ```

3. **创建多输出设备**
   - 打开 `/System/Applications/Utilities/Audio MIDI Setup.app`
   - 点击左下角 `+` → 创建多输出设备
   - 勾选你的物理扬声器/耳机 ✅
   - 勾选 BlackHole 2ch ✅
   - 确保物理设备排在第一位（拖动排序）

4. **设置系统输出**
   - 系统设置 → 声音 → 输出 → 选择刚创建的多输出设备

5. **验证**
   - 播放音乐，确认耳机有声音
   - 启动应用，确认能捕获到音频

### 注意

- macOS Ventura+ 的 Audio MIDI Setup 路径变为 `/System/Applications/Utilities/`
- 如果 BlackHole 不出现在设备列表中，需执行 `sudo killall coreaudiod`
- SIP 保护下 `launchctl` 命令可能被阻止，使用 `killall` 替代

---

## 翻译厂商接入指南

### MyMemory（默认，免费）

- **无需配置**，开箱即用
- 限制：匿名 5000 字符/天，注册邮箱可提升至 50000 字符/天
- 适合：开发调试、轻度使用
- API：`https://api.mymemory.translated.net/get`

### Ollama（本地部署，免费）

- 需要本地运行 Ollama 服务
- 配置：
  ```env
  TRANSLATOR_PROVIDER=ollama
  OLLAMA_BASE_URL=http://localhost:11434
  OLLAMA_MODEL=qwen2:7b-instruct
  ```
- 支持通过 ngrok 等隧道远程访问（需加 `ngrok-skip-browser-warning: true` 请求头）
- 适合：离线使用、无延迟顾虑
- API：`/api/chat`（Ollama 原生 API）

### 混元翻译（腾讯）

- 需要腾讯云 API 密钥
- 配置：
  ```env
  TRANSLATOR_PROVIDER=hunyuan
  HUNYUAN_SECRET_ID=your_id
  HUNYUAN_SECRET_KEY=your_key
  ```
- 注意：`HunyuanClient` 构造参数顺序为 `(credential, region)`
- system 消息必须位于消息列表最开始
- API：混元大模型 ChatCompletions

### DeepL

- 需要 DeepL API Key
- 配置：
  ```env
  TRANSLATOR_PROVIDER=deepl
  DEEPL_API_KEY=your_key
  ```

### 百度翻译

- 需要百度翻译开放平台 APP_ID 和 SECRET_KEY
- 配置：
  ```env
  TRANSLATOR_PROVIDER=baidu
  BAIDU_APP_ID=your_id
  BAIDU_SECRET_KEY=your_key
  ```

### OpenAI

- 需要 OpenAI API Key
- 配置：
  ```env
  TRANSLATOR_PROVIDER=openai
  OPENAI_API_KEY=your_key
  ```
- 默认使用 `gpt-4o-mini` 模型

### 翻译策略

- **无自动降级**：选择哪个厂商就只用哪个，失败直接报错
- **翻译缓存**：LRU 缓存（默认 500 条），相同文本不会重复调用
- **实时翻译**：partial 文本每 3 秒翻译一次，取最后 200 字符
- **429 限流防护**：检测到 429 错误自动暂停实时翻译 30 秒

---

## 流式识别架构详解

### 数据流

```
BlackHole 音频
    ↓ (sounddevice, 16kHz, int16, 0.1s/块)
音频回调 _audio_callback()
    ↓ (AcceptWaveform → 送入 vosk)
    ├── partial 结果 → asyncio.Queue → 主循环 → broadcast_partial() → 前端 LIVE 字幕
    └── final 结果   → asyncio.Queue → 主循环 → 累积文本
                                                    ↓ (1.5s 超时 / 5 词阈值)
                                              提交句子 → translate() → broadcast() → 前端历史字幕
```

### 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| SAMPLE_RATE | 16000 | 采样率 Hz |
| BLOCK_DURATION | 0.1 | 每个音频块时长 |
| SENTENCE_COMMIT_TIMEOUT | 1.5 | 句子提交超时（秒） |
| LIVE_TRANSLATE_INTERVAL | 3.0 | 实时翻译间隔（秒） |

### 句子提交条件

满足以下任一条件即提交：
1. 累积文本超过 **5 个单词** 且收到 final 结果
2. 距离上次收到文字超过 **1.5 秒**（超时提交）

### 前端显示

- **LIVE 区域**（底部，黄色边框）：实时更新 partial 文本 + LIVE 闪烁指示
- **历史区域**（上方滚动）：已提交的完整句子（英文 + 中文翻译）

---

## 前端交互说明

### 标题栏按钮

| 按钮 | 功能 |
|------|------|
| A- / A+ | 减小/增大字幕字体 |
| ◐ / ● | 降低/提高窗口透明度 |
| ⚙ | 打开设置弹窗 |
| 📍 / 📌 | 切换窗口置顶（📌 = 已置顶） |
| ✕ | 清空字幕 |

### 设置弹窗

- 点击翻译厂商即切换，即时生效无需重启
- 免费厂商标记「免费」徽章
- 当前选中的厂商显示「当前」徽章

### WebSocket 消息格式

```json
// 实时 partial（流式更新）
{
  "type": "subtitle",
  "text": "hello world",
  "zh": "",
  "final": false,
  "timestamp": "2026-06-12T..."
}

// 已提交字幕（完整句子）
{
  "type": "subtitle",
  "text": "hello world how are you",
  "zh": "你好世界，你好吗",
  "final": true,
  "timestamp": "2026-06-12T..."
}

// 切换厂商命令（前端 → 后端）
{
  "type": "command",
  "action": "switch_provider",
  "provider": "ollama"
}
```

---

## 常见问题排查

### 页面显示"等待音频输入"

1. 确认 BlackHole 已安装：`brew list blackhole-2ch`
2. 确认多输出设备已创建并设为系统输出
3. 确认有音频在播放（浏览器视频/音乐）
4. 检查终端日志是否有设备相关错误

### 翻译结果为空或报错

1. 确认 `.env` 中密钥配置正确
2. 如果使用 MyMemory，可能达到每日限额（5000 字符）
3. 如果使用 Ollama，确认服务已运行：`curl http://localhost:11434/`
4. 在设置弹窗切换到其他厂商测试

### 端口 8765 被占用

```bash
lsof -ti:8765 | xargs kill -9
```

### Rust 编译报错 edition2024

```bash
rustup update stable
# 需要 Rust 1.85+
```

### vosk 模型未找到

启动脚本会自动下载，也可手动：
```bash
cd backend/models
curl -L -o model.zip https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip model.zip && rm model.zip
```

---

## 配置参考

### 环境变量（.env 文件）

```env
# 翻译厂商选择
TRANSLATOR_PROVIDER=mymemory    # mymemory | ollama | hunyuan | deepl | baidu | openai

# 混元翻译
HUNYUAN_SECRET_ID=
HUNYUAN_SECRET_KEY=

# DeepL
DEEPL_API_KEY=

# 百度翻译
BAIDU_APP_ID=
BAIDU_SECRET_KEY=

# OpenAI
OPENAI_API_KEY=

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2:7b-instruct
```

### config.py 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| TRANSLATOR_PROVIDER | mymemory | 默认翻译厂商 |
| SAMPLE_RATE | 16000 | 音频采样率 |
| VOSK_MODEL_PATH | models/vosk-model-small-en-us-0.15 | vosk 模型路径 |
| SENTENCE_COMMIT_TIMEOUT | 1.5 | 句子提交超时（秒） |
| LIVE_TRANSLATE_INTERVAL | 3.0 | 实时翻译间隔（秒） |
| WS_HOST | localhost | WebSocket 地址 |
| WS_PORT | 8765 | WebSocket 端口 |
| TRANSLATION_CACHE_SIZE | 500 | LRU 缓存大小 |
