"""
panel.py
━━━━━━━━
偵測記錄面板與透明 Overlay 視窗模組。
包含：
  - TransparentOverlay：在 Chrome 上疊加的透明綠框視窗
  - TextPanel：右側 OCR 記錄面板（含 ✕ 關閉按鈕）
  - show_text_panel()：節流更新面板
  - pump_sleep()：替代 time.sleep，定期 pump tkinter 事件
"""

import time
import os
import threading
import tkinter as tk
from PIL import Image, ImageDraw, ImageFont, ImageTk

# pynput 全域快捷鍵（選用）
try:
    from pynput import keyboard as pynput_keyboard
    _PYNPUT_AVAILABLE = True
except ImportError:
    _PYNPUT_AVAILABLE = False

import logging
logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════
# 面板設定（從 chrome_ocr.py 匯入，這裡只提供預設值）
# ════════════════════════════════════════════════════════════

TEXT_PANEL_FONT_SIZE = 14
PANEL_HEADER_H       = 24
PANEL_HEADER_FONT_H  = 4
PANEL_LINE_GAP       = 5
PANEL_PADDING        = 8
CLOSE_BTN_SIZE       = 24
MAX_HISTORY          = 100
PANEL_THROTTLE       = 0.10

# ════════════════════════════════════════════════════════════
# 全域狀態
# ════════════════════════════════════════════════════════════

TEXT_HISTORY: list[str] = []
_overlay: "TransparentOverlay | None" = None
_text_panel: "TextPanel | None" = None
_quit_flag: bool = False
_last_panel_refresh: float = 0.0


def _set_quit() -> None:
    global _quit_flag
    _quit_flag = True


def is_quit() -> bool:
    return _quit_flag


def start_global_hotkey() -> None:
    """背景執行緒監聽 F12，不需視窗焦點即可關閉程式。"""
    if not _PYNPUT_AVAILABLE:
        logger.warning("pynput 未安裝，全域快捷鍵停用。可執行：uv add pynput")
        return

    def on_press(key):
        try:
            if key == pynput_keyboard.Key.f12:
                _set_quit()
                return False
        except Exception:
            pass

    t = threading.Thread(
        target=lambda: pynput_keyboard.Listener(on_press=on_press).join(),
        daemon=True,
    )
    t.start()


# ════════════════════════════════════════════════════════════
# pump_sleep
# ════════════════════════════════════════════════════════════

def pump_sleep(seconds: float, step: float = 0.016) -> None:
    """替代 time.sleep，每個 step 間隔 pump 一次 tkinter 事件。"""
    end = time.time() + seconds
    while True:
        remaining = end - time.time()
        if remaining <= 0:
            break
        time.sleep(min(step, remaining))
        if _overlay:
            _overlay.pump()


# ════════════════════════════════════════════════════════════
# 透明 Overlay 視窗
# ════════════════════════════════════════════════════════════

class TransparentOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        self.root.wm_attributes("-transparent", True)
        self.root.configure(bg="systemTransparent")
        self.root.withdraw()

        self.canvas = tk.Canvas(
            self.root,
            bg="systemTransparent",
            highlightthickness=0,
            cursor="none",
        )
        self.canvas.pack(fill="both", expand=True)
        self.root.bind_all("<Escape>", lambda _e: _set_quit())

        self._vw: int = 1
        self._vh: int = 1

    def set_viewport(self, x: int, y: int, w: int, h: int):
        self._vw, self._vh = w, h
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.canvas.config(width=w, height=h)
        self.root.deiconify()
        self.root.update()
        # 純 tkinter topmost，不使用 PyObjC（避免 SIGSEGV）
        self.root.wm_attributes("-topmost", True)
        self.root.lift()

    def raise_to_front(self):
        self.root.wm_attributes("-topmost", False)
        self.root.wm_attributes("-topmost", True)
        self.root.lift()
        self.root.update()

    def draw_boxes(self, boxes: list, scaled_w: int, scaled_h: int,
                   color: str = "#00ff00", thickness: int = 2):
        self.canvas.delete("all")
        sx = self._vw / scaled_w
        sy = self._vh / scaled_h
        for b in boxes:
            x1, x2 = b[0] * sx, b[1] * sx
            y1, y2 = b[2] * sy, b[3] * sy
            self.canvas.create_rectangle(
                x1 - 1, y1 - 1, x2 + 1, y2 + 1,
                outline="#003300", width=thickness + 2, fill=""
            )
            self.canvas.create_rectangle(
                x1, y1, x2, y2,
                outline=color, width=thickness, fill=""
            )
        self.root.update()

    def clear(self):
        self.canvas.delete("all")
        self.root.update()

    def pump(self):
        try:
            self.root.update()
        except tk.TclError:
            pass

    def destroy(self):
        try:
            self.root.destroy()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════
# 文字面板
# ════════════════════════════════════════════════════════════

class TextPanel:
    def __init__(self, root: tk.Tk, x: int, y: int, w: int, h: int):
        self._w, self._h = w, h
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        self.win.configure(bg="#0a100a")
        self.win.wm_attributes("-topmost", True)
        self.win.bind("<Escape>", lambda _e: _set_quit())

        # 右上角紅色 ✕ 關閉按鈕
        self._close_btn = tk.Button(
            self.win,
            text="✕",
            font=("Helvetica", max(CLOSE_BTN_SIZE // 3, 8), "bold"),
            fg="white",
            bg="#cc0000",
            activebackground="#ff3333",
            activeforeground="white",
            relief="flat",
            bd=0,
            cursor="hand2",
            command=_set_quit,
        )
        self._close_btn.place(
            x=w - CLOSE_BTN_SIZE - 4,
            y=4,
            width=CLOSE_BTN_SIZE,
            height=CLOSE_BTN_SIZE,
        )

        self._label = tk.Label(self.win, bg="#0a100a", borderwidth=0)
        self._label.place(x=0, y=0, width=w, height=h)
        self._close_btn.lift()

        self._photo: ImageTk.PhotoImage | None = None
        self.win.update()

    def refresh(self) -> None:
        pil_img = _render_text_panel_pil(self._w, self._h)
        self._photo = ImageTk.PhotoImage(pil_img)
        self._label.config(image=self._photo)
        self._close_btn.lift()
        self.win.update()


def _load_cjk_font(size: int):
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode MS.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _wrap_text(text: str, font, max_px: int, draw: ImageDraw.Draw) -> list[str]:
    if not text:
        return [""]
    lines, current = [], ""
    for ch in text:
        test = current + ch
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] > max_px and current:
            lines.append(current)
            current = ch
        else:
            current = test
    if current:
        lines.append(current)
    return lines or [""]


def _render_text_panel_pil(width: int, height: int) -> Image.Image:
    img = Image.new("RGB", (width, height), color=(10, 16, 10))
    draw = ImageDraw.Draw(img)
    font = _load_cjk_font(TEXT_PANEL_FONT_SIZE)

    draw.rectangle([(0, 0), (width, PANEL_HEADER_H)], fill=(0, 50, 0))
    draw.text((PANEL_PADDING, PANEL_HEADER_FONT_H), "OCR 偵測記錄",
              fill=(160, 255, 160), font=font)
    draw.line([(0, PANEL_HEADER_H), (width, PANEL_HEADER_H)],
              fill=(0, 100, 0), width=2)

    line_h    = TEXT_PANEL_FONT_SIZE + PANEL_LINE_GAP
    y_start   = PANEL_HEADER_H + 6
    max_lines = (height - y_start) // line_h

    flat: list[tuple[str, str]] = []
    for entry in reversed(TEXT_HISTORY):
        if entry.startswith("──"):
            flat.insert(0, (entry, "sep"))
        else:
            wrapped = list(reversed(
                _wrap_text(entry, font, width - PANEL_PADDING * 2, draw)
            ))
            for ln in wrapped:
                flat.insert(0, (ln, "text"))
        if len(flat) >= max_lines:
            break

    display = flat[-max_lines:]
    y = y_start
    for text, style in display:
        color = (0, 110, 0) if style == "sep" else (0, 220, 75)
        draw.text((PANEL_PADDING, y), text, fill=color, font=font)
        y += line_h

    return img


def show_text_panel() -> None:
    """節流：最快每 PANEL_THROTTLE 秒才真正 refresh 一次。"""
    global _last_panel_refresh
    now = time.time()
    if _overlay:
        _overlay.pump()
    if _text_panel and (now - _last_panel_refresh) >= PANEL_THROTTLE:
        _text_panel.refresh()
        _last_panel_refresh = now


# ════════════════════════════════════════════════════════════
# 初始化入口
# ════════════════════════════════════════════════════════════

def init_panel(screen_w: int, screen_h: int,
               chrome_w: int, chrome_x: int, chrome_y: int,
               panel_w: int) -> tuple["TransparentOverlay", "TextPanel"]:
    """
    建立 Overlay 和 TextPanel，回傳兩個物件。
    呼叫方需將回傳值存到 panel._overlay / panel._text_panel。
    """
    global _overlay, _text_panel

    overlay = TransparentOverlay()
    text_panel = TextPanel(
        overlay.root,
        x=chrome_x + chrome_w,
        y=chrome_y,
        w=panel_w,
        h=screen_h,
    )

    _overlay    = overlay
    _text_panel = text_panel

    show_text_panel()
    return overlay, text_panel
