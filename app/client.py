"""
Screen Stream Client (Windows)
================================
Захватывает экран, отправляет на сервер и показывает оверлей с ответами GPT.
Оверлей невидим для любого захвата экрана (dxcam, OBS, Zoom и т.д.)

Запуск:        python client.py
Запуск в фоне: pythonw client.py
"""

import asyncio
import ctypes
import sys
import threading
import time
import tkinter as tk
from datetime import datetime

import cv2
import dxcam
import websockets

# ── Настройки ──────────────────────────────────────────────────────────────────
SERVER_URL      = "wss://kege-station.store/ws/stream"
OVERLAY_URL     = "wss://kege-station.store/ws/overlay"
CAPTURE_FPS     = 1
JPEG_QUALITY    = 100
RECONNECT_DELAY = 3
LOG_FILE        = "client.log"

# Оверлей
OVERLAY_WIDTH   = 480
OVERLAY_OPACITY = 0.82
OVERLAY_BG      = "#0d0d0d"
OVERLAY_FG      = "#e8e8e8"
MAX_CHARS       = 800
# ───────────────────────────────────────────────────────────────────────────────

FRAME_INTERVAL = 1.0 / CAPTURE_FPS

WDA_EXCLUDEFROMCAPTURE = 0x00000011
user32 = ctypes.windll.user32


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if LOG_FILE:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")


# ─────────────────────────────────────────────────────────────────────────────
#  Оверлей
# ─────────────────────────────────────────────────────────────────────────────

class Overlay:
    def __init__(self):
        self.root = None
        self.label = None
        self.ready = threading.Event()

    def start(self):
        t = threading.Thread(target=self._run, daemon=True)
        t.start()
        self.ready.wait(timeout=5)

    def _run(self):
        self.root = tk.Tk()
        root = self.root

        root.overrideredirect(True)
        root.attributes('-topmost', True)
        root.attributes('-alpha', OVERLAY_OPACITY)
        root.configure(bg=OVERLAY_BG)
        root.resizable(False, False)

        sw = root.winfo_screenwidth()
        margin = 20
        x = sw - OVERLAY_WIDTH - margin
        root.geometry(f"{OVERLAY_WIDTH}x80+{x}+{margin}")

        pad_frame = tk.Frame(root, bg=OVERLAY_BG, padx=14, pady=12)
        pad_frame.pack(fill=tk.BOTH, expand=True)

        title = tk.Label(pad_frame, text="🤖 GPT", bg=OVERLAY_BG, fg="#555555",
                         font=("Segoe UI", 9, "bold"), anchor="w")
        title.pack(fill=tk.X, pady=(0, 6))

        self.label = tk.Label(pad_frame, text="Ожидание ответа GPT...",
                              bg=OVERLAY_BG, fg="#444444", font=("Segoe UI", 11),
                              wraplength=OVERLAY_WIDTH - 32, justify=tk.LEFT, anchor="nw")
        self.label.pack(fill=tk.BOTH, expand=True)

        # ── Перетаскивание ──
        self._drag_x = 0
        self._drag_y = 0

        def on_press(e):
            self._drag_x = e.x_root - root.winfo_x()
            self._drag_y = e.y_root - root.winfo_y()

        def on_drag(e):
            root.geometry(f"+{e.x_root - self._drag_x}+{e.y_root - self._drag_y}")

        for w in (pad_frame, title, self.label):
            w.bind("<ButtonPress-1>", on_press)
            w.bind("<B1-Motion>", on_drag)

        root.after(200, self._apply_capture_exclusion)
        self.ready.set()
        root.mainloop()

    def _apply_capture_exclusion(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            if hwnd == 0:
                hwnd = self.root.winfo_id()
            result = user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
            log("Оверлей: невидим для захвата экрана ✓" if result else "Оверлей: нужен Win10 2004+")
        except Exception as e:
            log(f"Оверлей: ошибка capture exclusion: {e}")

    def set_text(self, text: str):
        if not self.root or not self.label:
            return
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + "…"

        def _update():
            self.label.config(text=text, fg=OVERLAY_FG)
            self.root.update_idletasks()
            x = self.root.winfo_x()
            y = self.root.winfo_y()
            new_h = self.root.winfo_reqheight()
            max_h = self.root.winfo_screenheight() - y - 20
            self.root.geometry(f"{OVERLAY_WIDTH}x{min(new_h, max_h)}+{x}+{y}")

        try:
            self.root.after(0, _update)
        except Exception:
            pass

    def show_loading(self):
        try:
            self.root.after(0, lambda: self.label.config(text="⏳ GPT думает...", fg="#555555"))
        except Exception:
            pass


overlay = Overlay()


# ─────────────────────────────────────────────────────────────────────────────
#  WebSocket: захват экрана → сервер
# ─────────────────────────────────────────────────────────────────────────────

async def stream():
    camera = dxcam.create(output_color="BGR")
    camera.start(target_fps=CAPTURE_FPS)
    log(f"Захват экрана запущен ({CAPTURE_FPS} FPS)")

    while True:
        try:
            async with websockets.connect(
                SERVER_URL, ping_interval=None, ping_timeout=None, max_size=None,
            ) as ws:
                log("Стрим: подключено ✓")
                next_frame_at = time.monotonic()
                frame_count = 0
                start = time.monotonic()

                while True:
                    now = time.monotonic()
                    wait = next_frame_at - now
                    if wait > 0:
                        await asyncio.sleep(wait)
                    next_frame_at = time.monotonic() + FRAME_INTERVAL

                    frame = camera.get_latest_frame()
                    if frame is None:
                        continue

                    frame = cv2.resize(frame, (1440, 810), interpolation=cv2.INTER_LINEAR)
                    _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                    await ws.send(jpeg.tobytes())
                    frame_count += 1

                    elapsed = time.monotonic() - start
                    if frame_count % (CAPTURE_FPS * 30) == 0:
                        log(f"Работает {elapsed:.0f}s | Кадров: {frame_count} | FPS: {frame_count/elapsed:.1f}")

        except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            log(f"Стрим: обрыв: {e}. Переподключение через {RECONNECT_DELAY}s...")
            camera.stop()
            await asyncio.sleep(RECONNECT_DELAY)
            camera.start(target_fps=CAPTURE_FPS)
        except Exception as e:
            log(f"Стрим: ошибка: {e}. Переподключение через {RECONNECT_DELAY}s...")
            await asyncio.sleep(RECONNECT_DELAY)


# ─────────────────────────────────────────────────────────────────────────────
#  WebSocket: получение ответов GPT → оверлей
# ─────────────────────────────────────────────────────────────────────────────

async def overlay_listener():
    log(f"Оверлей: подключение к {OVERLAY_URL}...")
    while True:
        try:
            async with websockets.connect(
                OVERLAY_URL, ping_interval=None, ping_timeout=None,
            ) as ws:
                log("Оверлей: подключено ✓")
                async for message in ws:
                    if isinstance(message, str):
                        overlay.set_text(message)
        except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            log(f"Оверлей: обрыв: {e}. Переподключение через {RECONNECT_DELAY}s...")
            await asyncio.sleep(RECONNECT_DELAY)
        except Exception as e:
            log(f"Оверлей: ошибка: {e}. Переподключение через {RECONNECT_DELAY}s...")
            await asyncio.sleep(RECONNECT_DELAY)


async def main():
    await asyncio.gather(stream(), overlay_listener())


if __name__ == "__main__":
    log("Screen Stream Client запущен")
    overlay.start()
    log("Оверлей запущен")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Остановлен пользователем")
        sys.exit(0)