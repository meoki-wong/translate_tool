import { useEffect, useRef, useState, useCallback } from "react";

interface Subtitle {
  id: number;
  en: string;
  zh: string;
  timestamp: string;
}

interface WSMessage {
  type: "subtitle" | "status";
  en?: string;
  zh?: string;
  timestamp?: string;
  duration?: number;
  message?: string;
  status_type?: string;
  provider?: string;
}

const WS_URL = "ws://localhost:8765";

function App() {
  const [subtitles, setSubtitles] = useState<Subtitle[]>([]);
  const [status, setStatus] = useState<string>("等待连接...");
  const [connected, setConnected] = useState(false);
  const [fontSize, setFontSize] = useState(16);
  const [opacity, setOpacity] = useState(0.9);
  const wsRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const nextId = useRef(0);
  const reconnectTimer = useRef<number>(0);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      setStatus("已连接");
      console.log("WebSocket connected");
    };

    ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);

        if (msg.type === "subtitle" && msg.en) {
          const enText = msg.en;
          if (msg.zh) {
            // 翻译结果到了 - 更新最后一条字幕
            const zhText = msg.zh;
            setSubtitles((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last && last.en === enText) {
                last.zh = zhText;
              } else {
                updated.push({
                  id: nextId.current++,
                  en: enText,
                  zh: zhText,
                  timestamp: msg.timestamp || new Date().toISOString(),
                });
              }
              return updated.slice(-50);
            });
          } else {
            // 识别结果先到 - 立即显示英文
            const newSub: Subtitle = {
              id: nextId.current++,
              en: msg.en,
              zh: "...",
              timestamp: msg.timestamp || new Date().toISOString(),
            };
            setSubtitles((prev) => [...prev.slice(-50), newSub]);
          }
          setStatus("就绪");
        } else if (msg.type === "status") {
          setStatus(msg.message || "就绪");
        }
      } catch (e) {
        console.error("Failed to parse message:", e);
      }
    };

    ws.onclose = () => {
      setConnected(false);
      setStatus("连接断开，重连中...");
      // Auto reconnect after 3 seconds
      reconnectTimer.current = window.setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    // Delay connection to give Python backend time to start
    const timer = window.setTimeout(connect, 2000);
    return () => {
      clearTimeout(timer);
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  // Auto scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [subtitles]);

  return (
    <div
      className="app-container"
      style={{ opacity }}
    >
      {/* Title bar - draggable */}
      <div className="title-bar">
        <div className="title-bar-left">
          <span className={`status-dot ${connected ? "connected" : ""}`} />
          <span className="title-text">实时翻译</span>
        </div>
        <div className="title-bar-right">
          <span className="status-text">{status}</span>
          <button
            className="control-btn"
            onClick={() => setFontSize((s) => Math.max(12, s - 2))}
            title="减小字体"
          >
            A-
          </button>
          <button
            className="control-btn"
            onClick={() => setFontSize((s) => Math.min(28, s + 2))}
            title="增大字体"
          >
            A+
          </button>
          <button
            className="control-btn"
            onClick={() => setOpacity((o) => Math.max(0.3, +(o - 0.1).toFixed(1)))}
            title="降低透明度"
          >
            ◐
          </button>
          <button
            className="control-btn"
            onClick={() => setOpacity((o) => Math.min(1, +(o + 0.1).toFixed(1)))}
            title="提高透明度"
          >
            ●
          </button>
          <button
            className="control-btn close-btn"
            onClick={() => setSubtitles([])}
            title="清空"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Subtitle display area */}
      <div
        className="subtitle-area"
        ref={scrollRef}
        style={{ fontSize: `${fontSize}px` }}
      >
        {subtitles.length === 0 ? (
          <div className="empty-hint">
            <p>等待音频输入...</p>
            <p className="sub-hint">请确保 BlackHole 已配置且浏览器正在播放英文内容</p>
          </div>
        ) : (
          subtitles.map((sub) => (
            <div key={sub.id} className="subtitle-item">
              <div className="en-text">{sub.en}</div>
              <div className="zh-text">{sub.zh}</div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default App;
