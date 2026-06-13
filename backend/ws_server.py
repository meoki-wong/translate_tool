"""
WebSocket 服务端 - 将识别和翻译结果实时推送给前端
"""
import json
import asyncio
from datetime import datetime
from typing import Set

import websockets
import websockets.server

import config


class WSServer:
    """WebSocket 服务端，管理客户端连接并推送字幕"""

    def __init__(self):
        self._clients: Set[websockets.server.WebSocketServerProtocol] = set()
        self._server = None
        self._on_command = None  # 回调函数，处理客户端命令

    def set_command_handler(self, handler):
        """设置客户端命令处理回调"""
        self._on_command = handler

    async def _handler(self, websocket):
        """处理客户端连接"""
        self._clients.add(websocket)
        addr = websocket.remote_address
        print(f"[WS] 客户端已连接: {addr} (当前连接数: {len(self._clients)})")
        try:
            # 发送欢迎消息
            await websocket.send(json.dumps({
                "type": "status",
                "message": "已连接到翻译服务",
                "provider": config.TRANSLATOR_PROVIDER,
                "source_lang": config.SOURCE_LANG,
                "target_lang": config.TARGET_LANG,
            }))
            # 监听客户端消息
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if data.get("type") == "command" and self._on_command:
                        await self._on_command(data, websocket)
                except (json.JSONDecodeError, Exception) as e:
                    print(f"[WS] 处理客户端消息失败: {e}")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            print(f"[WS] 客户端已断开: {addr} (当前连接数: {len(self._clients)})")

    async def broadcast(self, en_text: str, zh_text: str):
        """向所有客户端广播已提交字幕（final）"""
        if not self._clients:
            return

        message = json.dumps({
            "type": "subtitle",
            "text": en_text,
            "zh": zh_text,
            "final": True,
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False)

        await self._send_all(message)

    async def broadcast_partial(self, en_text: str, zh_text: str = ""):
        """向所有客户端广播实时识别中间结果（partial）"""
        if not self._clients:
            return

        message = json.dumps({
            "type": "subtitle",
            "text": en_text,
            "zh": zh_text,
            "final": False,
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False)

        await self._send_all(message)

    async def _send_all(self, message: str):
        """向所有客户端发送消息，移除断开的连接"""
        disconnected = set()
        for client in self._clients:
            try:
                await client.send(message)
            except websockets.exceptions.ConnectionClosed:
                disconnected.add(client)
        self._clients -= disconnected

    async def broadcast_status(self, status_type: str, message: str):
        """广播状态消息"""
        if not self._clients:
            return
        data = json.dumps({
            "type": "status",
            "status_type": status_type,
            "message": message,
        }, ensure_ascii=False)

        await self._send_all(data)

    async def start(self):
        """启动 WebSocket 服务"""
        self._server = await websockets.serve(
            self._handler,
            config.WS_HOST,
            config.WS_PORT,
        )
        print(f"[WS] WebSocket 服务已启动: ws://{config.WS_HOST}:{config.WS_PORT}")

    async def stop(self):
        """停止 WebSocket 服务"""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        print("[WS] WebSocket 服务已停止")
