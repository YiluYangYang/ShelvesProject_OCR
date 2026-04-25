"""
browser.py
━━━━━━━━━━
Chrome Remote Debugging 控制模組。
包含：
  - init_browser()：啟動 / 連線 Chrome，開啟所有目標分頁
  - browse_tab()：瀏覽單一分頁（滾動、截圖、OCR、動畫）
  - tab_loop()：網頁循環主邏輯（依序巡覽 URLS）
  - human_scroll() / grab_browser() 等輔助函式
"""

import time
import random
import math
import socket
import subprocess
import logging

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
import os

import panel as p   # 依賴 panel.py

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
# Chrome 設定（由 chrome_ocr.py 覆寫）
# ════════════════════════════════════════════════════════════

CHROME_APP             = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_DEBUG_PORT      = 9222
CHROME_DEBUG_USER_DATA = "/Users/yilu/selenium-chrome"
CHROME_PROFILE_DIR     = "Default"


# ════════════════════════════════════════════════════════════
# Chrome 連線
# ════════════════════════════════════════════════════════════

def _is_debug_port_open() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = s.connect_ex(("127.0.0.1", CHROME_DEBUG_PORT)) == 0
    s.close()
    return result


def _launch_chrome_debug() -> None:
    cmd = [
        CHROME_APP,
        f"--remote-debugging-port={CHROME_DEBUG_PORT}",
        f"--user-data-dir={CHROME_DEBUG_USER_DATA}",
        f"--profile-directory={CHROME_PROFILE_DIR}",
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
    """連接已開啟的 Chrome，確保所有目標分頁都已開啟。"""
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

    for url in urls:
        if _get_handle_for_url(driver, url) is None:
            driver.execute_script(f"window.open('{url}', '_blank');")
            p.pump_sleep(1.5)

    h = _get_handle_for_url(driver, urls[0])
    if h:
        driver.switch_to.window(h)

    return driver


# ════════════════════════════════════════════════════════════
# 瀏覽器工具
# ════════════════════════════════════════════════════════════

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
    """截圖，最多 retry 3 次。"""
    from selenium.common.exceptions import TimeoutException
    for attempt in range(3):
        try:
            buf = np.frombuffer(driver.get_screenshot_as_png(), np.uint8)
            return cv2.imdecode(buf, cv2.IMREAD_COLOR)
        except TimeoutException:
            if attempt < 2:
                logger.warning(f"截圖 timeout，重試 ({attempt + 1}/3)...")
                p.pump_sleep(1.0)
            else:
                raise


def human_scroll(driver: webdriver.Chrome, total_px: int, duration: float):
    """模擬真人正弦緩動捲動。"""
    N = 30
    weights = [math.sin(math.pi * (i + 0.5) / N) for i in range(N)]
    total_w = sum(weights)
    base_delay = duration / N

    for w in weights:
        px    = total_px * w / total_w * random.uniform(0.85, 1.15)
        delay = base_delay * random.uniform(0.75, 1.30)
        try:
            driver.execute_script(
                f"window.scrollBy({{top:{px:.1f},left:0,behavior:'instant'}});"
            )
        except Exception:
            pass
        p.pump_sleep(max(0.02, delay))


# ════════════════════════════════════════════════════════════
# OCR
# ════════════════════════════════════════════════════════════

def scale_image(frame: np.ndarray, scale: float) -> np.ndarray:
    if scale == 1.0:
        return frame
    return cv2.resize(frame, (int(frame.shape[1] * scale), int(frame.shape[0] * scale)))


def detect_boxes(reader: easyocr.Reader, image: np.ndarray) -> list:
    horizontal_list, _ = reader.detect(image)
    return horizontal_list[0] if horizontal_list and len(horizontal_list) > 0 else []


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
            if p._overlay and last_boxes:
                p._overlay.draw_boxes(last_boxes, scaled_w, scaled_h)
            p.show_text_panel()

        if p.is_quit():
            return last_boxes
        p.pump_sleep(0.01)

    return last_boxes


def post_ocr_scan_animation(results: list[dict], detected_boxes: list,
                             duration: float, interval: float,
                             scaled_w: int, scaled_h: int) -> None:
    if not results:
        return

    if len(results) <= 3:
        if p._overlay:
            p._overlay.draw_boxes([r["box"] for r in results], scaled_w, scaled_h)
        end = time.time() + duration
        while time.time() < end:
            p.show_text_panel()
            if p.is_quit():
                return
            p.pump_sleep(0.02)
    else:
        total_cycles = max(1, int(duration / (interval * len(results))))
        for _ in range(total_cycles):
            for r in results:
                if p._overlay:
                    p._overlay.draw_boxes([r["box"]], scaled_w, scaled_h)
                p.show_text_panel()
                if p.is_quit():
                    return
                p.pump_sleep(interval)


# ════════════════════════════════════════════════════════════
# 終端機顯示
# ════════════════════════════════════════════════════════════

def display_results(console: Console, results: list[dict], url: str,
                    round_idx: int, tab_idx: int, total_tabs: int,
                    max_history: int = 100) -> None:
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
        p.TEXT_HISTORY.append(r["text"])

    if len(p.TEXT_HISTORY) > max_history:
        del p.TEXT_HISTORY[: len(p.TEXT_HISTORY) - max_history]

    console.print(Rule(style="green"))
    console.print(f"[dim]  共辨識 {len(results)} 個文字段落 | 按 ESC / F12 / ✕ 結束[/dim]")


# ════════════════════════════════════════════════════════════
# 核心流程：瀏覽單一分頁
# ════════════════════════════════════════════════════════════

def browse_tab(driver: webdriver.Chrome, reader: easyocr.Reader,
               console: Console, url: str, tab_idx: int,
               total_tabs: int, round_counter: list[int],
               tab_duration: float, scroll_interval: float,
               scroll_amount: int, scroll_duration: float,
               frame_scale: float, visual_duration: float,
               visual_refresh: float, post_ocr_duration: float,
               post_ocr_interval: float, max_history: int) -> bool:
    """瀏覽單一分頁 tab_duration 秒。回傳 False 表示應結束。"""
    tab_start = time.time()
    next_scroll_time = tab_start + 1.5

    console.print(
        f"\n[bold green]► 切換至分頁 {tab_idx + 1}/{total_tabs}[/bold green]"
        f"  [dim]{url}[/dim]"
    )
    short_url = url.split("//")[-1].split("/")[0]
    p.TEXT_HISTORY.append(f"── Tab {tab_idx + 1}  {short_url} ──")

    if p._overlay:
        try:
            vx, vy, vw, vh = get_viewport_rect(driver)
            p._overlay.set_viewport(vx, vy, vw, vh)
        except Exception as e:
            logger.warning(f"viewport 查詢失敗: {e}")

    while time.time() - tab_start < tab_duration:
        while time.time() < next_scroll_time:
            p.show_text_panel()
            if p.is_quit():
                return False
            p.pump_sleep(0.05)

        if p._overlay:
            p._overlay.clear()
        human_scroll(driver, scroll_amount, scroll_duration)
        next_scroll_time = time.time() + scroll_interval - scroll_duration

        if p._overlay:
            p._overlay.raise_to_front()

        frame = grab_browser(driver)
        scaled = scale_image(frame, frame_scale)
        sw, sh = scaled.shape[1], scaled.shape[0]
        detected_boxes = detect_boxes(reader, scaled)
        logger.info(f"偵測框數: {len(detected_boxes)}")

        if len(detected_boxes) <= 3:
            p.show_text_panel()
            if p._overlay:
                p._overlay.clear()
            continue

        round_counter[0] += 1

        final_boxes = visual_effect(detected_boxes, visual_duration, visual_refresh, sw, sh)
        if p.is_quit():
            return False
        if not final_boxes:
            continue

        results = recognize(reader, scaled, final_boxes)
        display_results(console, results, url, round_counter[0],
                        tab_idx, total_tabs, max_history)
        post_ocr_scan_animation(results, detected_boxes,
                                post_ocr_duration, post_ocr_interval, sw, sh)

        if p._overlay:
            p._overlay.clear()
        if p.is_quit():
            return False

    return True


# ════════════════════════════════════════════════════════════
# 網頁循環主邏輯
# ════════════════════════════════════════════════════════════

def tab_loop(driver: webdriver.Chrome, reader: easyocr.Reader,
             console: Console, urls: list[str],
             tab_duration: float, scroll_interval: float,
             scroll_amount: int, scroll_duration: float,
             frame_scale: float, visual_duration: float,
             visual_refresh: float, post_ocr_duration: float,
             post_ocr_interval: float, max_history: int) -> int:
    """
    依序巡覽 urls，每個分頁停留 tab_duration 秒後切換下一個。
    回傳總執行輪數。按 ESC / F12 / ✕ 停止。
    """
    round_counter = [0]
    tab_idx = 0

    while True:
        url = urls[tab_idx % len(urls)]

        handle = _get_handle_for_url(driver, url)
        if handle is None:
            driver.execute_script(f"window.open('{url}', '_blank');")
            p.pump_sleep(1.5)
            handle = _get_handle_for_url(driver, url)

        if handle:
            driver.switch_to.window(handle)
        p.pump_sleep(1.0)

        ok = browse_tab(
            driver, reader, console,
            url, tab_idx % len(urls), len(urls),
            round_counter,
            tab_duration, scroll_interval,
            scroll_amount, scroll_duration,
            frame_scale, visual_duration,
            visual_refresh, post_ocr_duration,
            post_ocr_interval, max_history,
        )

        if not ok:
            break

        tab_idx += 1

    return round_counter[0]
