"""
Screen Stream Client (Windows)
================================
Захватывает экран и отправляет кадры на сервер по WebSocket.

Запуск обычный:   python client.py
Запуск в фоне:    pythonw client.py  (или run_hidden.vbs)
"""

import asyncio
import sys
import time
from datetime import datetime

import cv2
import dxcam
import websockets

# ── Настройки ──────────────────────────────────────────────────────────────────
SERVER_URL    = "wss://kege-station.store/ws/stream"
CAPTURE_FPS   = 1      # кадров в секунду
JPEG_QUALITY  = 100     # качество (0-100) было 80
RECONNECT_DELAY = 3    # секунд до переподключения
LOG_FILE      = "client.log"   # None — не писать лог
# ───────────────────────────────────────────────────────────────────────────────

FRAME_INTERVAL = 1.0 / CAPTURE_FPS


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if LOG_FILE:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")


async def stream():
    camera = dxcam.create(output_color="BGR")
    camera.start(target_fps=CAPTURE_FPS)
    log(f"Захват экрана запущен ({CAPTURE_FPS} FPS)")
    log(f"Подключение к {SERVER_URL}...")

    while True:
        try:
            async with websockets.connect(
                SERVER_URL,
                ping_interval=None,
                ping_timeout=None,
                max_size=None,
            ) as ws:
                log("Подключено! Начинаю трансляцию...")
                frame_count = 0
                start = time.monotonic()
                next_frame_at = time.monotonic()

                while True:
                    # Точное ограничение FPS
                    now = time.monotonic()
                    wait = next_frame_at - now
                    if wait > 0:
                        await asyncio.sleep(wait)
                    next_frame_at = time.monotonic() + FRAME_INTERVAL

                    TARGET_WIDTH = 1440 #1920 на 1080
                    TARGET_HEIGHT = 810
                    frame = camera.get_latest_frame()
                    if frame is None:
                        continue

                    # ── Ресайз до 720p ────────────────────────────────
                    frame = cv2.resize(
                        frame,
                        (TARGET_WIDTH, TARGET_HEIGHT),
                        interpolation=cv2.INTER_LINEAR  # быстрее чем INTER_AREA, качество ок
                    )

                    if frame is None:
                        continue

                    _, jpeg = cv2.imencode(
                        ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
                    )
                    await ws.send(jpeg.tobytes())
                    frame_count += 1

                    # Лог каждые 30 секунд
                    elapsed = time.monotonic() - start
                    if frame_count % (CAPTURE_FPS * 30) == 0:
                        log(f"Работает {elapsed:.0f}s | Кадров: {frame_count} | FPS: {frame_count/elapsed:.1f}")

        except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            log(f"Соединение прервано: {e}. Переподключение через {RECONNECT_DELAY}s...")
            camera.stop()
            await asyncio.sleep(RECONNECT_DELAY)
            camera.start(target_fps=CAPTURE_FPS)
        except Exception as e:
            log(f"Ошибка: {e}. Переподключение через {RECONNECT_DELAY}s...")
            await asyncio.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    log("Screen Stream Client запущен")
    try:
        asyncio.run(stream())
    except KeyboardInterrupt:
        log("Остановлен пользователем")
        sys.exit(0)