#!/usr/bin/env python3
"""
Chrome網頁OCR偵測系統 (Mac版)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
功能：
  1. Chrome 佔螢幕左 3/4，右 1/4 為文字紀錄面板
  2. 透明 Overlay 視窗直接在 Chrome 畫面上繪製綠框
  3. 人工滾輪：正弦緩動 + 隨機抖動，像真人在捲動
  4. 偵測到文字框後隨機綠框輪播，OCR 後逐一掃描動畫
  5. 按 ESC、F12 或右上角 ✕ 結束

執行方式（使用 uv）：
  uv run chrome_ocr.py

修正說明：
  - [FIX-1] pump_sleep()：所有 time.sleep 改為分段 pump，避免 tkinter 主執行緒飢餓
  - [FIX-2] show_text_panel() 加節流（throttle）
  - [FIX-3] TEXT_HISTORY 加上限（MAX_HISTORY = 100）
  - [FIX-4] 完全移除 PyObjC，改用純 tkinter topmost（避免 SIGSEGV crash）
  - [FIX-7] grab_browser 加 retry（最多 3 次）
  - [FIX-9] main() 分頁切換改用 URL 網域比對

新增功能：
  - [NEW-1] 關閉按鈕：文字面板右上角顯示 ✕；全域 F12 快捷鍵（需 pynput）
  - [NEW-3] Chrome Remote Debugging 登入：啟動獨立 Chrome
            （user-data-dir 指向 /Users/yilu/selenium-chrome）

使用登入步驟（只需做一次）：
  1. 執行腳本，Chrome 會自動啟動
  2. 在彈出的 Chrome 視窗手動登入 Facebook / Instagram
  3. 登入後直接繼續執行，下次啟動會自動帶入登入狀態
"""

import time
import random
import math
import os
import tkinter as tk
import cv2
import numpy as np
import easyocr
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.rule import Rule
from PIL import Image, ImageDraw, ImageFont, ImageTk
import logging
import threading

# [NEW-1] pynput 全域快捷鍵（不需視窗焦點）
try:
    from pynput import keyboard as pynput_keyboard
    _PYNPUT_AVAILABLE = True
except ImportError:
    _PYNPUT_AVAILABLE = False

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════
# 可調整參數
# ════════════════════════════════════════════════════════════

URLS = [
    "https://www.facebook.com/",
    "https://www.instagram.com/",
    "https://tw.news.yahoo.com/archive",
    "https://www.reddit.com/",
]

TAB_DURATION        = 40.0   # 每個分頁停留秒數
SCROLL_INTERVAL     = 5.0    # 兩次滑動之間的等待秒數
SCROLL_AMOUNT       = 700    # 每次滑動總距離 (px)
SCROLL_DURATION     = 2.8    # 每次滑動花費秒數（越大越絲滑）

VISUAL_DURATION     = 4.5    # 視覺效果持續秒數（綠框輪播）
VISUAL_REFRESH      = 0.32   # 每次重新隨機選框間隔
POST_OCR_DURATION   = 4.0    # OCR 後逐一掃描動畫持續秒數
POST_OCR_INTERVAL   = 0.55   # 每個框停留時間（>3 段文字時）

FRAME_SCALE         = 0.70   # 截圖縮放比例（降低 OCR 運算量）
OCR_LANGUAGES       = ['en', 'ch_tra']
USE_GPU             = False
SHOW_ALL_DETECTED   = False  # True = 顯示全部偵測框（藍色）

# ── 視窗佈局 ──────────────────────────────────────────────
SCREEN_W        = 1792
SCREEN_H        = 1440
CHROME_W        = SCREEN_W * 3 // 4   # = 1344
CHROME_H        = SCREEN_H            # = 1440
PANEL_W         = SCREEN_W - CHROME_W # = 448
CHROME_X        = 0
CHROME_Y        = 0

# UI 尺寸
TEXT_PANEL_FONT_SIZE = 14
PANEL_HEADER_H       = 24
PANEL_HEADER_FONT_H  = 4
PANEL_LINE_GAP       = 5
PANEL_PADDING        = 8
CLOSE_BTN_SIZE       = 24

# TEXT_HISTORY 最大保留筆數
MAX_HISTORY = 100

# 文字面板 refresh 節流間隔（秒）
PANEL_THROTTLE = 0.10

# ════════════════════════════════════════════════════════════
# Chrome Remote Debugging 設定
# ════════════════════════════════════════════════════════════

CHROME_APP             = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_DEBUG_PORT      = 9222
CHROME_DEBUG_USER_DATA = "/Users/yilu/selenium-chrome"

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


def _start_global_hotkey() -> None:
    """[NEW-1] 背景執行緒監聽 F12，不需視窗焦點即可關閉程式。"""
    if not _PYNPUT_AVAILABLE:
        logger.warning("pynput 未安裝，全域快捷鍵停用。可執行：pip install pynput")
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
# pump_sleep：替代 time.sleep，定期 pump tkinter 事件
# ════════════════════════════════════════════════════════════

def pump_sleep(seconds: float, step: float = 0.016) -> None:
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
        self._setup_native_window()

    def _setup_native_window(self):
        """[FIX-4] 完全移除 PyObjC，避免 SIGSEGV crash。"""
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

        # [NEW-1] 右上角紅色 ✕ 關閉按鈕
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

    # 從尾端展開，只處理剛好填滿畫面需要的行數
    line_h  = TEXT_PANEL_FONT_SIZE + PANEL_LINE_GAP
    y_start = PANEL_HEADER_H + 6
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
# Chrome 控制（Remote Debugging）
# ════════════════════════════════════════════════════════════

def _is_debug_port_open() -> bool:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = s.connect_ex(("127.0.0.1", CHROME_DEBUG_PORT)) == 0
    s.close()
    return result


def _launch_chrome_debug() -> None:
    """用 Remote Debugging 模式啟動 Chrome。"""
    import subprocess
    cmd = [
        CHROME_APP,
        f"--remote-debugging-port={CHROME_DEBUG_PORT}",
        f"--user-data-dir={CHROME_DEBUG_USER_DATA}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    subprocess.Popen(cmd)
    for _ in range(20):
        time.sleep(0.5)
        if _is_debug_port_open():
            return
    raise RuntimeError(f"Chrome 啟動逾時，debug port {CHROME_DEBUG_PORT} 未開啟")


def _get_handle_for_url(driver: webdriver.Chrome, target_url: str) -> str | None:
    """用網域比對找到對應的分頁 handle。"""
    target_domain = target_url.split("//")[-1].split("/")[0].lstrip("www.")
    current_handle = driver.current_window_handle
    for h in driver.window_handles:
        try:
            driver.switch_to.window(h)
            if target_domain in driver.current_url:
                return h
        except Exception:
            continue
    try:
        driver.switch_to.window(current_handle)
    except Exception:
        pass
    return None


def init_browser(urls: list[str]) -> webdriver.Chrome:
    """連接已開啟的 Chrome（Remote Debugging 模式）。"""
    if not _is_debug_port_open():
        logger.info("Chrome debug port 未開啟，自動啟動 Chrome...")
        _launch_chrome_debug()

    opts = Options()
    opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{CHROME_DEBUG_PORT}")

    from selenium.common.exceptions import WebDriverException
    try:
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=opts,
        )
    except WebDriverException as e:
        raise RuntimeError(f"Selenium 連線 Chrome 失敗: {e}") from e

    # 確保所有目標網頁都已開啟
    for url in urls:
        if _get_handle_for_url(driver, url) is None:
            driver.execute_script(f"window.open('{url}', '_blank');")
            pump_sleep(1.5)

    # 切到第一個目標網頁
    h = _get_handle_for_url(driver, urls[0])
    if h:
        driver.switch_to.window(h)

    return driver


def get_viewport_rect(driver: webdriver.Chrome) -> tuple[int, int, int, int]:
    info = driver.execute_script("""
        return {
            sx: window.screenX,
            sy: window.screenY,
            ow: window.outerWidth,
            oh: window.outerHeight,
            iw: window.innerWidth,
            ih: window.innerHeight
        };
    """)
    toolbar_h = info["oh"] - info["ih"]
    return (
        int(info["sx"]),
        int(info["sy"]) + toolbar_h,
        int(info["iw"]),
        int(info["ih"]),
    )


def grab_browser(driver: webdriver.Chrome) -> np.ndarray:
    """加 retry，避免 renderer 單次 timeout 就 crash。"""
    from selenium.common.exceptions import TimeoutException
    for attempt in range(3):
        try:
            buf = np.frombuffer(driver.get_screenshot_as_png(), np.uint8)
            return cv2.imdecode(buf, cv2.IMREAD_COLOR)
        except TimeoutException:
            if attempt < 2:
                logger.warning(f"截圖 timeout，重試 ({attempt + 1}/3)...")
                pump_sleep(1.0)
            else:
                raise


def human_scroll(driver: webdriver.Chrome, total_px: int, duration: float):
    """模擬真人滾輪捲動（正弦緩動 + 隨機擾動）。"""
    N = 30
    weights = [math.sin(math.pi * (i + 0.5) / N) for i in range(N)]
    total_w = sum(weights)
    base_delay = duration / N

    for w in weights:
        px = total_px * w / total_w * random.uniform(0.85, 1.15)
        delay = base_delay * random.uniform(0.75, 1.30)
        try:
            driver.execute_script(
                f"window.scrollBy({{top:{px:.1f},left:0,behavior:'instant'}});"
            )
        except Exception:
            pass
        pump_sleep(max(0.02, delay))


# ════════════════════════════════════════════════════════════
# OCR 相關
# ════════════════════════════════════════════════════════════

def scale_image(frame: np.ndarray, scale: float) -> np.ndarray:
    if scale == 1.0:
        return frame
    return cv2.resize(frame, (int(frame.shape[1] * scale), int(frame.shape[0] * scale)))


def detect_boxes(reader: easyocr.Reader, image: np.ndarray) -> list:
    horizontal_list, _ = reader.detect(image)
    if horizontal_list and len(horizontal_list) > 0:
        return horizontal_list[0]
    return []


def pick_random_boxes(boxes: list, n_min: int = 3, n_max: int = 5) -> list:
    total = len(boxes)
    if total < n_min:
        return []
    count = random.randint(n_min, min(n_max, total))
    idx = np.random.choice(total, count, replace=False)
    return [boxes[i] for i in idx]


def recognize(reader: easyocr.Reader, image: np.ndarray, boxes: list) -> list[dict]:
    results = []
    for b in boxes:
        x_min, x_max, y_min, y_max = map(int, b)
        crop = image[y_min:y_max, x_min:x_max]
        if crop.size == 0:
            continue
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        out = reader.readtext(rgb, detail=0, paragraph=False)
        text = " ".join(out).strip() if out else ""
        if text:
            results.append({"box": list(map(int, b)), "text": text})
    return results


# ════════════════════════════════════════════════════════════
# 視覺動畫
# ════════════════════════════════════════════════════════════

def check_esc() -> bool:
    if _overlay:
        _overlay.pump()
    return _quit_flag


def visual_effect(detected_boxes: list, duration: float, refresh_interval: float,
                  scaled_w: int, scaled_h: int) -> list:
    last_boxes: list = []
    last_refresh = 0.0
    start = time.time()

    while time.time() - start < duration:
        now = time.time()
        if now - last_refresh >= refresh_interval:
            selected = pick_random_boxes(detected_boxes)
            if selected:
                last_boxes = selected
            last_refresh = now
            if _overlay and last_boxes:
                _overlay.draw_boxes(last_boxes, scaled_w, scaled_h)
            show_text_panel()

        if check_esc():
            return last_boxes
        pump_sleep(0.01)

    return last_boxes


def post_ocr_scan_animation(results: list[dict], detected_boxes: list,
                             duration: float, interval: float,
                             scaled_w: int, scaled_h: int) -> None:
    if not results:
        return

    if len(results) <= 3:
        if _overlay:
            _overlay.draw_boxes([r["box"] for r in results], scaled_w, scaled_h)
        end = time.time() + duration
        while time.time() < end:
            show_text_panel()
            if check_esc():
                return
            pump_sleep(0.02)
    else:
        total_cycles = max(1, int(duration / (interval * len(results))))
        for _ in range(total_cycles):
            for r in results:
                if _overlay:
                    _overlay.draw_boxes([r["box"]], scaled_w, scaled_h)
                show_text_panel()
                if check_esc():
                    return
                pump_sleep(interval)


# ════════════════════════════════════════════════════════════
# 終端機顯示
# ════════════════════════════════════════════════════════════

def display_results(console: Console, results: list[dict], url: str,
                    round_idx: int, tab_idx: int, total_tabs: int) -> None:
    os.system("clear")
    header = Text()
    header.append(f"  Tab {tab_idx + 1}/{total_tabs}  ", style="bold white on dark_green")
    header.append(f"  Round #{round_idx}  ", style="bold white on blue")
    header.append(f"  {url}", style="dim")
    console.print(header)
    console.print(Rule(style="green"))

    if not results:
        console.print("[dim]  (未偵測到文字)[/dim]")
        return

    for i, r in enumerate(results, 1):
        console.print(Panel(
            Text(r["text"], style="bright_white"),
            title=f"[green]段落 {i}[/green]",
            border_style="green",
            padding=(0, 2),
        ))
        TEXT_HISTORY.append(r["text"])

    if len(TEXT_HISTORY) > MAX_HISTORY:
        del TEXT_HISTORY[: len(TEXT_HISTORY) - MAX_HISTORY]

    console.print(Rule(style="green"))
    console.print(f"[dim]  共辨識 {len(results)} 個文字段落 | 按 ESC / F12 / ✕ 結束[/dim]")


# ════════════════════════════════════════════════════════════
# 核心流程：瀏覽單一分頁
# ════════════════════════════════════════════════════════════

def browse_tab(driver: webdriver.Chrome, reader: easyocr.Reader,
               console: Console, url: str, tab_idx: int,
               total_tabs: int, round_counter: list[int]) -> bool:
    """瀏覽單一分頁 TAB_DURATION 秒。回傳 False 表示應結束。"""
    tab_start = time.time()
    next_scroll_time = tab_start + 1.5

    console.print(
        f"\n[bold green]► 切換至分頁 {tab_idx + 1}/{total_tabs}[/bold green]"
        f"  [dim]{url}[/dim]"
    )
    short_url = url.split("//")[-1].split("/")[0]
    TEXT_HISTORY.append(f"── Tab {tab_idx + 1}  {short_url} ──")

    if _overlay:
        try:
            vx, vy, vw, vh = get_viewport_rect(driver)
            _overlay.set_viewport(vx, vy, vw, vh)
        except Exception as e:
            logger.warning(f"viewport 查詢失敗: {e}")

    while time.time() - tab_start < TAB_DURATION:
        while time.time() < next_scroll_time:
            show_text_panel()
            if check_esc():
                return False
            pump_sleep(0.05)

        if _overlay:
            _overlay.clear()
        human_scroll(driver, SCROLL_AMOUNT, SCROLL_DURATION)
        next_scroll_time = time.time() + SCROLL_INTERVAL - SCROLL_DURATION

        if _overlay:
            _overlay.raise_to_front()

        frame = grab_browser(driver)
        scaled = scale_image(frame, FRAME_SCALE)
        sw, sh = scaled.shape[1], scaled.shape[0]
        detected_boxes = detect_boxes(reader, scaled)
        logger.info(f"偵測框數: {len(detected_boxes)}")

        if len(detected_boxes) <= 3:
            show_text_panel()
            if _overlay:
                _overlay.clear()
            continue

        round_counter[0] += 1

        final_boxes = visual_effect(
            detected_boxes, VISUAL_DURATION, VISUAL_REFRESH, sw, sh
        )
        if check_esc():
            return False
        if not final_boxes:
            continue

        results = recognize(reader, scaled, final_boxes)
        display_results(console, results, url, round_counter[0], tab_idx, total_tabs)
        post_ocr_scan_animation(
            results, detected_boxes, POST_OCR_DURATION, POST_OCR_INTERVAL, sw, sh
        )

        if _overlay:
            _overlay.clear()
        if check_esc():
            return False

    return True


# ════════════════════════════════════════════════════════════
# 主程式
# ════════════════════════════════════════════════════════════

def main():
    global _overlay, _text_panel

    console = Console()
    console.print(Panel(
        "[bold green]Chrome OCR 偵測系統[/bold green]\n"
        f"Chrome: {CHROME_W}×{CHROME_H}pts  |  "
        f"文字面板: {PANEL_W}pts  |  "
        f"滑動: {SCROLL_AMOUNT}px / {SCROLL_DURATION}s\n"
        "[dim]按 ESC / F12 / 右上角 ✕ 結束[/dim]",
        border_style="green",
    ))

    console.print("[dim]初始化視窗...[/dim]")
    _start_global_hotkey()
    _overlay = TransparentOverlay()

    _text_panel = TextPanel(
        _overlay.root,
        x=CHROME_X + CHROME_W,
        y=CHROME_Y,
        w=PANEL_W,
        h=SCREEN_H,
    )
    show_text_panel()
    console.print("[green]✓ 視窗就緒[/green]")

    console.print("[dim]初始化 EasyOCR...[/dim]")
    reader = easyocr.Reader(OCR_LANGUAGES, gpu=USE_GPU)
    console.print("[green]✓ EasyOCR 就緒[/green]")

    console.print("[dim]啟動 Chrome...[/dim]")
    driver = init_browser(URLS)
    console.print("[green]✓ Chrome 就緒[/green]")
    pump_sleep(2.0)

    round_counter = [0]
    tab_idx = 0
    running = True

    try:
        while running:
            url = URLS[tab_idx % len(URLS)]

            handle = _get_handle_for_url(driver, url)
            if handle is None:
                driver.execute_script(f"window.open('{url}', '_blank');")
                pump_sleep(1.5)
                handle = _get_handle_for_url(driver, url)

            if handle:
                driver.switch_to.window(handle)
            pump_sleep(1.0)

            ok = browse_tab(
                driver, reader, console,
                url, tab_idx % len(URLS), len(URLS),
                round_counter,
            )

            if not ok:
                running = False
                break

            tab_idx += 1

    except KeyboardInterrupt:
        console.print("\n[yellow]收到 Ctrl+C，結束中...[/yellow]")
    finally:
        if _overlay:
            _overlay.destroy()
        try:
            # 程式結束前清除所有分頁的 cookie
            console.print("[dim]清除 cookie 中...[/dim]")
            for handle in driver.window_handles:
                try:
                    driver.switch_to.window(handle)
                    driver.delete_all_cookies()
                except Exception:
                    pass
            console.print("[green]✓ Cookie 已清除[/green]")
        except Exception as e:
            logger.warning(f"清除 cookie 失敗: {e}")
        try:
            driver.quit()
        except Exception:
            pass
        console.print(
            f"\n[bold green]程式結束。共執行 {round_counter[0]} 輪 OCR 偵測。[/bold green]"
        )


if __name__ == "__main__":
    main()
