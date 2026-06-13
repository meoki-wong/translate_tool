import { useEffect, useRef, useState, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";

interface Subtitle {
  id: number;
  en: string;
  zh: string;
  timestamp: string;
}

interface WSMessage {
  type: "subtitle" | "status" | "provider_info";
  text?: string;
  zh?: string;
  final?: boolean;
  timestamp?: string;
  message?: string;
  status_type?: string;
  provider?: string;
}

interface ProviderInfo {
  id: string;
  name: string;
  desc: string;
  needKey: boolean;
}

const WS_URL = "ws://localhost:8765";

const PROVIDERS: ProviderInfo[] = [
  { id: "mymemory", name: "MyMemory", desc: "免费无需密钥，速度快", needKey: false },
  { id: "ollama", name: "Ollama", desc: "本地部署，无需联网", needKey: false },
  { id: "hunyuan", name: "混元翻译", desc: "腾讯大模型，质量高", needKey: true },
  { id: "deepl", name: "DeepL", desc: "高质量，需 API Key", needKey: true },
  { id: "baidu", name: "百度翻译", desc: "需 APP_ID", needKey: true },
  { id: "openai", name: "OpenAI", desc: "GPT 翻译", needKey: true },
];

function App() {
  const [history, setHistory] = useState<Subtitle[]>([]);
  const [liveEn, setLiveEn] = useState("");
  const [liveZh, setLiveZh] = useState("");
  const [status, setStatus] = useState<string>("等待连接...");
  const [connected, setConnected] = useState(false);
  const [fontSize, setFontSize] = useState(16);
  const [opacity, setOpacity] = useState(0.9);
  const [showSettings, setShowSettings] = useState(false);
  const [currentProvider, setCurrentProvider] = useState("mymemory");
  const [isPinned, setIsPinned] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const nextId = useRef(0);
  const reconnectTimer = useRef<number>(0);

  // Send command to backend via WebSocket
  const sendCommand = useCallback((action: string, data: Record<string, string>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "command", action, ...data }));
    }
  }, []);

  const switchProvider = useCallback((provider: string) => {
    sendCommand("switch_provider", { provider });
    setCurrentProvider(provider);
    setShowSettings(false);
    setStatus(`切换翻译: ${provider}`);
  }, [sendCommand]);

  // Toggle always on top
  const togglePin = useCallback(async () => {
    try {
      const newVal = await invoke<boolean>("toggle_always_on_top");
      setIsPinned(newVal);
    } catch (e) {
      console.error("Toggle pin failed:", e);
    }
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      setStatus("已连接");
    };

    ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);

        if (msg.type === "subtitle" && msg.text) {
          if (msg.final) {
            // 已提交的完整句子 → 加入历史，清空 live
            const newSub: Subtitle = {
              id: nextId.current++,
              en: msg.text,
              zh: msg.zh || "",
              timestamp: msg.timestamp || new Date().toISOString(),
            };
            setHistory((prev) => [...prev.slice(-30), newSub]);
            setLiveEn("");
            setLiveZh("");
          } else {
            // 实时 partial → 更新英文 + 投机翻译中文（如有）
            setLiveEn(msg.text);
            if (msg.zh) {
              setLiveZh(msg.zh);
            }
          }
          setStatus("就绪");
        } else if (msg.type === "status") {
          setStatus(msg.message || "就绪");
          if (msg.provider) {
            setCurrentProvider(msg.provider);
          }
        } else if (msg.type === "provider_info") {
          if (msg.provider) {
            setCurrentProvider(msg.provider);
          }
        }
      } catch (e) {
        console.error("Failed to parse message:", e);
      }
    };

    ws.onclose = () => {
      setConnected(false);
      setStatus("连接断开，重连中...");
      reconnectTimer.current = window.setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(connect, 2000);
    return () => {
      clearTimeout(timer);
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [history, liveEn, liveZh]);

  return (
    <div className="app-container" style={{ opacity }}>
      {/* Title bar */}
      <div className="title-bar">
        <div className="title-bar-left">
          <span className={`status-dot ${connected ? "connected" : ""}`} />
          <span className="title-text">实时翻译</span>
          <span className="provider-label">{currentProvider}</span>
        </div>
        <div className="title-bar-right">
          <span className="status-text">{status}</span>
          <button className="control-btn" onClick={() => setFontSize((s) => Math.max(12, s - 2))} title="减小字体">A-</button>
          <button className="control-btn" onClick={() => setFontSize((s) => Math.min(28, s + 2))} title="增大字体">A+</button>
          <button className="control-btn" onClick={() => setOpacity((o) => Math.max(0.3, +(o - 0.1).toFixed(1)))} title="降低透明度">◐</button>
          <button className="control-btn" onClick={() => setOpacity((o) => Math.min(1, +(o + 0.1).toFixed(1)))} title="提高透明度">●</button>
          <button className="control-btn" onClick={() => setShowSettings((s) => !s)} title="设置">⚙</button>
          <button className={`control-btn ${isPinned ? "pinned-btn" : ""}`} onClick={togglePin} title={isPinned ? "取消置顶" : "置顶"}>{isPinned ? "📌" : "📍"}</button>
          <button className="control-btn close-btn" onClick={() => { setHistory([]); setLiveEn(""); setLiveZh(""); }} title="清空">✕</button>
        </div>
      </div>

      {/* Settings Modal */}
      {showSettings && (
        <div className="settings-overlay" onClick={() => setShowSettings(false)}>
          <div className="settings-modal" onClick={(e) => e.stopPropagation()}>
            <div className="settings-header">
              <span>翻译设置</span>
              <button className="settings-close" onClick={() => setShowSettings(false)}>✕</button>
            </div>
            <div className="settings-section">
              <div className="settings-label">翻译服务</div>
              <div className="provider-list">
                {PROVIDERS.map((p) => (
                  <div
                    key={p.id}
                    className={`provider-item ${currentProvider === p.id ? "active" : ""}`}
                    onClick={() => switchProvider(p.id)}
                  >
                    <div className="provider-name">
                      {p.name}
                      {currentProvider === p.id && <span className="provider-badge">当前</span>}
                      {!p.needKey && <span className="provider-free">免费</span>}
                    </div>
                    <div className="provider-desc">{p.desc}</div>
                  </div>
                ))}
              </div>
            </div>
            <div className="settings-footer">
              <span className="settings-hint">切换后即时生效，无需重启</span>
            </div>
          </div>
        </div>
      )}

      {/* Subtitle display area */}
      <div className="subtitle-area" ref={scrollRef} style={{ fontSize: `${fontSize}px` }}>
        {history.length === 0 && !liveEn ? (
          <div className="empty-hint">
            <p>等待音频输入...</p>
            <p className="sub-hint">请确保 BlackHole 已配置且浏览器正在播放英文内容</p>
          </div>
        ) : (
          <>
            {/* 已提交的历史字幕 */}
            {history.map((sub) => (
              <div key={sub.id} className="subtitle-item">
                <div className="en-text">{sub.en}</div>
                <div className="zh-text">{sub.zh}</div>
              </div>
            ))}
            {/* 实时流式字幕 */}
            {liveEn && (
              <div className="subtitle-item live-item">
                <div className="en-text">{liveEn}</div>
                {liveZh && <div className="zh-text">{liveZh}</div>}
                <div className="live-indicator">LIVE</div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default App;
