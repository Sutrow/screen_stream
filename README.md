server
"""
Screen Stream Server
====================
Принимает кадры от клиента по WebSocket, сохраняет видео и отдаёт live-стрим в браузер.

Запуск: python server.py
Открыть в браузере: http://localhost:8080
"""

import asyncio
import base64
import os
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

# ── Настройки ──────────────────────────────────────────────────────────────────
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8080
RECORDINGS_DIR = Path("recordings")
JPEG_QUALITY = 70          # качество сжатия для просмотра в браузере (0-100)
VIDEO_FPS = 5              # FPS сохраняемого видео
# ───────────────────────────────────────────────────────────────────────────────

RECORDINGS_DIR.mkdir(exist_ok=True)

app = FastAPI()

# Активные браузерные подключения для live-просмотра
viewers: set[WebSocket] = set()

# Состояние текущей сессии
session = {
    "active": False,
    "writer": None,
    "frame_count": 0,
    "start_time": None,
    "filename": None,
}


def create_video_writer(width: int, height: int) -> tuple[cv2.VideoWriter, str]:
    """Создаёт новый VideoWriter для записи сессии."""
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = str(RECORDINGS_DIR / f"session_{ts}.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(filename, fourcc, VIDEO_FPS, (width, height))
    return writer, filename


async def broadcast_to_viewers(data: bytes):
    """Рассылает кадр всем подключённым браузерам."""
    dead = set()
    for ws in viewers:
        try:
            await ws.send_bytes(data)
        except Exception:
            dead.add(ws)
    viewers.difference_update(dead)


# ── HTML страница просмотра ────────────────────────────────────────────────────
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
  span#fps, span#resolution, span#frames { color: #888; }
</style>
</head>
<body>
<header>
  <h1>🖥 Screen Stream</h1>
  <span class="badge" id="status">Ожидание...</span>
  <span class="info">Сервер запущен | Запись: <span id="rec-name">—</span></span>
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
  <span>Разрешение: <span id="resolution">—</span></span>
  <span>Кадров получено: <span id="frames">0</span></span>
</footer>

<script>
  const img = document.getElementById('screen');
  const placeholder = document.getElementById('placeholder');
  const statusBadge = document.getElementById('status');
  const fpsEl = document.getElementById('fps');
  const resEl = document.getElementById('resolution');
  const framesEl = document.getElementById('frames');
  const recEl = document.getElementById('rec-name');

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
      if (typeof e.data === 'string') {
        // JSON-метаданные
        try {
          const meta = JSON.parse(e.data);
          if (meta.filename) recEl.textContent = meta.filename;
          if (meta.resolution) resEl.textContent = meta.resolution;
        } catch {}
        return;
      }
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
      // Переподключение через 2 секунды
      setTimeout(connect, 2000);
    };
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
    # Отправляем текущее имя файла если сессия активна
    if session["active"] and session["filename"]:
        await ws.send_text(f'{{"filename": "{Path(session["filename"]).name}"}}')
    try:
        while True:
            await asyncio.sleep(10)  # держим соединение
    except (WebSocketDisconnect, Exception):
        viewers.discard(ws)



'''
@app.websocket("/ws/stream")
async def ws_stream(ws: WebSocket):
    """Клиент подключается сюда для отправки кадров."""
    await ws.accept()
    print(f"[{datetime.now():%H:%M:%S}] Клиент подключился")

    session["active"] = True
    session["frame_count"] = 0
    session["start_time"] = time.time()
    session["writer"] = None  # создадим при первом кадре

    loop = asyncio.get_event_loop()

    try:
        while True:
            data = await ws.receive_bytes()

            # Декодируем кадр
            arr = np.frombuffer(data, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                continue

            h, w = frame.shape[:2]

            # Инициализируем VideoWriter при первом кадре
            if session["writer"] is None:
                writer, filename = create_video_writer(w, h)
                session["writer"] = writer
                session["filename"] = filename
                print(f"[{datetime.now():%H:%M:%S}] Запись: {filename} ({w}x{h})")

                # Уведомляем всех зрителей
                await broadcast_to_viewers(
                    f'{{"filename": "{Path(filename).name}", "resolution": "{w}x{h}"}}'.encode()
                )

            # Пишем кадр в видео (в отдельном потоке чтобы не блокировать)
            await loop.run_in_executor(None, session["writer"].write, frame)

            session["frame_count"] += 1

            # Пережимаем для браузера и рассылаем зрителям
            _, jpeg = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
            )
            await broadcast_to_viewers(jpeg.tobytes())

    except (WebSocketDisconnect, Exception) as e:
        print(f"[{datetime.now():%H:%M:%S}] Клиент отключился: {e}")
    finally:
        if session["writer"]:
            session["writer"].release()
            elapsed = time.time() - session["start_time"]
            print(
                f"[{datetime.now():%H:%M:%S}] Сессия завершена. "
                f"Кадров: {session['frame_count']}, "
                f"Длительность: {elapsed:.1f}s, "
                f"Файл: {session['filename']}"
            )
        session["active"] = False
        session["writer"] = None
'''
@app.websocket("/ws/stream")
async def ws_stream(ws: WebSocket):
    await ws.accept()
    print(f"[{datetime.now():%H:%M:%S}] Клиент подключился")

    try:
        while True:
            data = await ws.receive_bytes()
            # Просто пересылаем кадр всем зрителям без сохранения
            await broadcast_to_viewers(data)

    except (WebSocketDisconnect, Exception) as e:
        print(f"[{datetime.now():%H:%M:%S}] Клиент отключился: {e}")

if __name__ == "__main__":
    print(f"🖥  Screen Stream Server")
    print(f"   Адрес:    http://{SERVER_HOST}:{SERVER_PORT}")
    print(f"   Записи:   {RECORDINGS_DIR.resolve()}")
    print("-" * 40)
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT, log_level="warning")




client
"""
Screen Stream Client (Windows)
================================
Захватывает экран и отправляет кадры на сервер по WebSocket.
Работает как фоновый процесс без GUI.

Запуск обычный:        python client.py
Запуск в фоне:         pythonw client.py
                       (или запустите run_hidden.vbs)
"""

import asyncio
import sys
import time
from datetime import datetime

import cv2
import dxcam
import numpy as np
import websockets

# ── Настройки ──────────────────────────────────────────────────────────────────
SERVER_URL = "ws://127.0.0.1:8080/ws/stream"   # ← укажите адрес сервера
CAPTURE_FPS = 1          # кадров в секунду (рекомендуется 3-10)
JPEG_QUALITY = 80         # качество кадра при отправке (0-100)
MONITOR_INDEX = 1         # 1 = основной монитор, 2 = второй монитор и т.д.
RECONNECT_DELAY = 3       # секунд до попытки переподключения
LOG_FILE = "client.log"   # путь к лог-файлу (None — не писать лог)
# ───────────────────────────────────────────────────────────────────────────────

FRAME_INTERVAL = 1.0 / CAPTURE_FPS


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if LOG_FILE:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")

'''
def capture_frame(sct: mss.mss, monitor: dict) -> bytes | None:
    """Захватывает один кадр и возвращает JPEG-байты."""
    try:
        img = sct.grab(monitor)
        # mss возвращает BGRA → конвертируем в BGR для OpenCV
        frame = cv2.cvtColor(np.array(img), cv2.COLOR_BGRA2BGR)
        _, jpeg = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
        )
        return jpeg.tobytes()
    except Exception as e:
        log(f"Ошибка захвата кадра: {e}")
        return None
'''

async def stream():
    camera = dxcam.create(output_color="BGR")
    camera.start(target_fps=CAPTURE_FPS)
    log(f"Захват экрана запущен ({CAPTURE_FPS} FPS)")
    log(f"Подключение к {SERVER_URL}...")

    while True:
        try:
            async with websockets.connect(
                SERVER_URL,
                ping_interval=20,
                ping_timeout=10,
                max_size=None,
            ) as ws:
                log("Подключено! Начинаю трансляцию...")
                frame_count = 0
                start = time.monotonic()

                while True:
                    frame = camera.get_latest_frame()
                    if frame is None:
                        await asyncio.sleep(0.01)
                        continue

                    _, jpeg = cv2.imencode(
                        ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
                    )
                    await ws.send(jpeg.tobytes())
                    frame_count += 1

                    if frame_count % (CAPTURE_FPS * 30) == 0:
                        elapsed = time.monotonic() - start
                        log(f"Работает {elapsed:.0f}s | Кадров: {frame_count} | FPS: {frame_count/elapsed:.1f}")

        except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            log(f"Соединение прервано: {e}. Переподключение через {RECONNECT_DELAY}s...")
            camera.stop()
            camera.start(target_fps=CAPTURE_FPS)
            await asyncio.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    log("Screen Stream Client запущен")
    try:
        asyncio.run(stream())
    except KeyboardInterrupt:
        log("Остановлен пользователем")
        sys.exit(0)