#!/usr/bin/env python3
"""
chrome_ocr.py
━━━━━━━━━━━━━
主程式入口：組裝 panel.py 與 browser.py 並啟動系統。

執行方式：
  uv run chrome_ocr.py

模組結構：
  chrome_ocr.py  ← 這個檔案，負責設定與啟動
  panel.py       ← 偵測記錄面板、Overlay 視窗
  browser.py     ← Chrome 控制、分頁開啟、網頁循環
"""

import logging
import easyocr
from rich.console import Console
from rich.panel import Panel

import panel as p
import browser as b

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════
# 可調整參數
# ════════════════════════════════════════════════════════════

# 目標網站（依序循環）
URLS = [
    "https://www.facebook.com/",
    "https://www.instagram.com/",
    "https://x.com/home",
    "https://tw.news.yahoo.com/archive",
    "https://www.reddit.com/",
]

# 瀏覽行為
TAB_DURATION      = 40.0   # 每個分頁停留秒數
SCROLL_INTERVAL   = 5.0    # 兩次滾動間的等待秒數
SCROLL_AMOUNT     = 700    # 每次滾動距離 (px)
SCROLL_DURATION   = 2.8    # 一次滾動持續時間（越大越像真人）

# OCR
FRAME_SCALE       = 0.70   # 截圖縮放比例（越小越省 CPU）
OCR_LANGUAGES     = ['en', 'ch_tra']
USE_GPU           = False

# 視覺效果
VISUAL_DURATION   = 4.5    # 綠框輪播秒數
VISUAL_REFRESH    = 0.32   # 輪播重新選框間隔
POST_OCR_DURATION = 4.0    # OCR 後掃描動畫秒數
POST_OCR_INTERVAL = 0.55   # 掃描動畫每框停留時間

# 視窗佈局
SCREEN_W  = 1792
SCREEN_H  = 1120
CHROME_W  = SCREEN_W * 3 // 4   # = 1344
CHROME_H  = SCREEN_H
PANEL_W   = SCREEN_W - CHROME_W # = 448
CHROME_X  = 0
CHROME_Y  = 0

# 面板外觀（覆寫 panel.py 預設值）
p.TEXT_PANEL_FONT_SIZE = 14
p.PANEL_HEADER_H       = 24
p.PANEL_HEADER_FONT_H  = 4
p.PANEL_LINE_GAP       = 5
p.PANEL_PADDING        = 8
p.CLOSE_BTN_SIZE       = 24
p.MAX_HISTORY          = 100
p.PANEL_THROTTLE       = 0.10

# Chrome Remote Debugging（覆寫 browser.py 預設值）
b.CHROME_APP             = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
b.CHROME_DEBUG_PORT      = 9222
b.CHROME_DEBUG_USER_DATA = "/Users/<YOUR_USERNAME>/selenium-chrome"
b.CHROME_PROFILE_DIR     = "Default"


# ════════════════════════════════════════════════════════════
# 主程式
# ════════════════════════════════════════════════════════════

def main():
    console = Console()
    console.print(Panel(
        "[bold green]Chrome OCR 偵測系統[/bold green]\n"
        f"Chrome: {CHROME_W}×{CHROME_H}pts  |  "
        f"文字面板: {PANEL_W}pts  |  "
        f"滑動: {SCROLL_AMOUNT}px / {SCROLL_DURATION}s\n"
        "[dim]按 ESC / F12 / 右上角 ✕ 結束[/dim]",
        border_style="green",
    ))

    # 初始化視窗
    console.print("[dim]初始化視窗...[/dim]")
    p.start_global_hotkey()
    p.init_panel(SCREEN_W, SCREEN_H, CHROME_W, CHROME_X, CHROME_Y, PANEL_W)
    console.print("[green]✓ 視窗就緒[/green]")

    # 初始化 EasyOCR
    console.print("[dim]初始化 EasyOCR...[/dim]")
    reader = easyocr.Reader(OCR_LANGUAGES, gpu=USE_GPU)
    console.print("[green]✓ EasyOCR 就緒[/green]")

    # 啟動 Chrome
    console.print("[dim]啟動 Chrome...[/dim]")
    driver = b.init_browser(URLS)
    console.print("[green]✓ Chrome 就緒[/green]")
    p.pump_sleep(2.0)

    # 執行網頁循環
    total_rounds = 0
    try:
        total_rounds = b.tab_loop(
            driver, reader, console, URLS,
            tab_duration      = TAB_DURATION,
            scroll_interval   = SCROLL_INTERVAL,
            scroll_amount     = SCROLL_AMOUNT,
            scroll_duration   = SCROLL_DURATION,
            frame_scale       = FRAME_SCALE,
            visual_duration   = VISUAL_DURATION,
            visual_refresh    = VISUAL_REFRESH,
            post_ocr_duration = POST_OCR_DURATION,
            post_ocr_interval = POST_OCR_INTERVAL,
            max_history       = p.MAX_HISTORY,
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]收到 Ctrl+C，結束中...[/yellow]")
    finally:
        if p._overlay:
            p._overlay.destroy()
        try:
            driver.quit()
        except Exception:
            pass
        console.print(
            f"\n[bold green]程式結束。共執行 {total_rounds} 輪 OCR 偵測。[/bold green]"
        )


if __name__ == "__main__":
    main()