"""
Screen Stream Server
====================
Принимает кадры от клиента по WebSocket и отдаёт live-стрим в браузер.
Запуск: python server.py
Открыть в браузере: http://localhost:8080
"""

import asyncio
from datetime import datetime

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

# ── Настройки ──────────────────────────────────────────────────────────────────
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8080
# ───────────────────────────────────────────────────────────────────────────────

app = FastAPI()

# Активные браузерные подключения для live-просмотра
viewers: set[WebSocket] = set()


async def broadcast_to_viewers(data: bytes):
    """Рассылает кадр всем подключённым браузерам."""
    dead = set()
    for ws in viewers:
        try:
            await ws.send_bytes(data)
        except Exception:
            dead.add(ws)
    viewers.difference_update(dead)


HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Screen Stream</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #0f0f0f; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; height: 100vh; display: flex; flex-direction: column; }
  header { padding: 12px 20px; background: #1a1a1a; border-bottom: 1px solid #333; display: flex; align-items: center; gap: 16px; }
  h1 { font-size: 16px; font-weight: 600; color: #fff; }
  .badge { font-size: 12px; padding: 3px 10px; border-radius: 20px; background: #2a2a2a; color: #888; }
  .badge.live { background: #ff3b3b22; color: #ff5555; animation: pulse 1.5s infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
  .info { font-size: 12px; color: #555; margin-left: auto; }
  .screen-wrap { flex: 1; display: flex; align-items: center; justify-content: center; padding: 16px; overflow: hidden; }
  #screen { max-width: 100%; max-height: 100%; border-radius: 6px; box-shadow: 0 8px 40px #000a; display: none; }
  .placeholder { text-align: center; color: #444; }
  .placeholder svg { width: 64px; height: 64px; margin-bottom: 16px; }
  .placeholder p { font-size: 14px; }
  footer { padding: 8px 20px; background: #1a1a1a; border-top: 1px solid #222; display: flex; gap: 24px; font-size: 12px; color: #555; }
  span#fps, span#frames { color: #888; }
</style>
</head>
<body>
<header>
  <h1>🖥 Screen Stream</h1>
  <span class="badge" id="status">Ожидание...</span>
  <span class="info" id="resolution"></span>
  <button id="copy-btn" onclick="copyFrame()" style="margin-left:12px; padding:4px 14px; background:#2a2a2a; color:#ccc; border:1px solid #444; border-radius:6px; cursor:pointer; font-size:12px;">📋 Копировать</button>
</header>
<div class="screen-wrap">
  <img id="screen" alt="stream"/>
  <div class="placeholder" id="placeholder">
    <svg viewBox="0 0 24 24" fill="none" stroke="#444" stroke-width="1.5">
      <rect x="2" y="3" width="20" height="14" rx="2"/>
      <path d="M8 21h8M12 17v4"/>
    </svg>
    <p>Ожидание подключения клиента...</p>
  </div>
</div>
<footer>
  <span>FPS: <span id="fps">—</span></span>
  <span>Кадров получено: <span id="frames">0</span></span>
</footer>

<script>
  const img = document.getElementById('screen');
  const placeholder = document.getElementById('placeholder');
  const statusBadge = document.getElementById('status');
  const fpsEl = document.getElementById('fps');
  const framesEl = document.getElementById('frames');

  let frameCount = 0;
  let lastFpsTime = Date.now();
  let lastFpsCount = 0;

  function connect() {
    const ws = new WebSocket(`ws://${location.host}/ws/view`);
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
      statusBadge.textContent = '● LIVE';
      statusBadge.className = 'badge live';
    };

    ws.onmessage = (e) => {
      const blob = new Blob([e.data], { type: 'image/jpeg' });
      const url = URL.createObjectURL(blob);
      img.onload = () => URL.revokeObjectURL(url);
      img.src = url;
      img.style.display = 'block';
      placeholder.style.display = 'none';

      frameCount++;
      framesEl.textContent = frameCount;

      const now = Date.now();
      if (now - lastFpsTime >= 1000) {
        fpsEl.textContent = (frameCount - lastFpsCount).toFixed(0);
        lastFpsTime = now;
        lastFpsCount = frameCount;
      }
    };

    ws.onclose = () => {
      statusBadge.textContent = 'Отключено';
      statusBadge.className = 'badge';
      img.style.display = 'none';
      placeholder.style.display = 'block';
      setTimeout(connect, 2000);
    };
  }
  
  async function copyFrame() {
    const btn = document.getElementById('copy-btn');
    try {
      const canvas = document.createElement('canvas');
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      canvas.getContext('2d').drawImage(img, 0, 0);
      canvas.toBlob(async (blob) => {
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
        btn.textContent = '✅ Скопировано!';
        setTimeout(() => btn.textContent = '📋 Копировать', 2000);
      });
    } catch (e) {
      btn.textContent = '❌ Ошибка';
      setTimeout(() => btn.textContent = '📋 Копировать', 2000);
    }
  }
  connect();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML


@app.websocket("/ws/view")
async def ws_view(ws: WebSocket):
    """Браузер подключается сюда для просмотра стрима."""
    await ws.accept()
    viewers.add(ws)
    try:
        while True:
            await asyncio.sleep(10)
    except (WebSocketDisconnect, Exception):
        viewers.discard(ws)


@app.websocket("/ws/stream")
async def ws_stream(ws: WebSocket):
    """Клиент подключается сюда для отправки кадров."""
    await ws.accept()
    print(f"[{datetime.now():%H:%M:%S}] Клиент подключился")
    try:
        while True:
            data = await ws.receive_bytes()
            await broadcast_to_viewers(data)
    except (WebSocketDisconnect, Exception) as e:
        print(f"[{datetime.now():%H:%M:%S}] Клиент отключился: {e}")


if __name__ == "__main__":
    print("🖥  Screen Stream Server (без записи)")
    print(f"   Адрес: http://localhost:{SERVER_PORT}")
    print("-" * 40)
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT, log_level="warning")