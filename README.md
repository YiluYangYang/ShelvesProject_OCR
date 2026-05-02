# Chrome OCR 偵測系統

自動瀏覽社群網站（Facebook、Instagram、Reddit、Yahoo 等），即時截圖並用 EasyOCR 識別畫面中的文字，過濾左右側欄只掃描主內容區域，將結果顯示於右側記錄面板。

---

## 模組結構

```
chrome_ocr.py   ← 主程式入口：所有參數設定與啟動流程
panel.py        ← 偵測記錄面板、透明 Overlay 視窗、CPU 監控
browser.py      ← Chrome 控制、分頁開啟、OCR 掃描、網頁循環
chrome_login_test.py  ← 獨立登入測試工具（不含 OCR）
```

執行方式：
```bash
uv run chrome_ocr.py
```

---

## 目錄

1. [Python 版本需求](#1-python-版本需求)
2. [環境準備與安裝](#2-環境準備與安裝)
3. [Chrome Profile 初始設定](#3-chrome-profile-初始設定)
4. [可調整參數說明](#4-可調整參數說明)
5. [效能優化建議](#5-效能優化建議)
6. [uv 套件管理](#6-uv-套件管理)

---

## 1. Python 版本需求

| 項目 | 需求 |
|------|------|
| **Python** | **3.12 以上**（`pyproject.toml` 指定 `>=3.12`） |
| macOS | 13 Ventura 以上 |
| Google Chrome | 任意近期版本 |
| 記憶體 | 8 GB（建議 16 GB） |

> Python 3.12 以下不支援部分型別提示語法（如 `str | None`），會直接報 SyntaxError。

---

## 2. 環境準備與安裝

### Mac ARM（Apple Silicon）— M1 / M2 / M3 / M4

```bash
# 安裝 uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.zshrc

# clone 並安裝
git clone https://github.com/YiluYangYang/ShelvesProject_OCR.git
cd ShelvesProject_OCR
uv sync

# 選用套件
uv add pynput   # F12 全域快捷鍵
uv add psutil   # 標題列 CPU 使用率
```

ARM 上 PyTorch wheel 由 uv 自動選取，不需手動指定。

### Mac Intel（x86_64）— 2020 年以前機型

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.zshrc

git clone https://github.com/YiluYangYang/ShelvesProject_OCR.git
cd ShelvesProject_OCR
uv sync
uv add pynput psutil
```

> Intel Mac 的 PyTorch 最高支援 `torch 2.2.x`，`pyproject.toml` 已鎖定，直接 `uv sync` 即可。
> 若系統安裝了 Anaconda，確認使用 uv 的虛擬環境：
> ```bash
> which python  # 應顯示 .venv/bin/python
> ```

### 驗證安裝

```bash
uv run python -c "import easyocr, cv2, selenium, tkinter; print('✓ 所有核心套件正常')"
```

---

## 3. Chrome Profile 初始設定

### 原理

程式以 **Chrome Remote Debugging** 模式啟動一個獨立的 Chrome，profile 存放於 `~/selenium-chrome`，與平常使用的 Chrome 完全隔離。第一次需要手動登入，之後登入狀態永久保留。

### 初次設定流程

**步驟 1：修改 `chrome_ocr.py` 中的路徑**

```python
# Chrome Remote Debugging（覆寫 browser.py 預設值）
b.CHROME_APP             = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
b.CHROME_DEBUG_PORT      = 9222
b.CHROME_DEBUG_USER_DATA = "/Users/<YOUR_USERNAME>/selenium-chrome"  # 改這行
b.CHROME_PROFILE_DIR     = "Default"
```

查詢你的使用者名稱：
```bash
whoami
```

**步驟 2：第一次執行並手動登入**

```bash
uv run chrome_ocr.py
```

程式啟動後 Chrome 會自動開啟，在 Chrome 視窗中依序登入 Facebook、Instagram 等網站。

**步驟 3：驗證登入狀態**

使用獨立的登入測試工具：
```bash
uv run chrome_login_test.py
```

輸出範例：
```
━━ 結果總覽 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  www.facebook.com               ✅ 已登入
  www.instagram.com              ✅ 已登入
  www.reddit.com                 ✅ 已登入
```

### 環境重置（遇到 Chrome 無法啟動時）

```bash
pkill -f "Google Chrome"; pkill -f chromedriver
sleep 2
rm -f ~/selenium-chrome/SingletonLock
rm -f ~/selenium-chrome/Default/LOCK
uv run chrome_ocr.py
```

---

## 4. 可調整參數說明

所有參數集中在 `chrome_ocr.py` 開頭，修改後直接存檔執行即可。

### 目標網站

```python
URLS = [
    "https://www.facebook.com/",
    "https://www.instagram.com/",
    "https://tw.news.yahoo.com/archive",
    "https://www.reddit.com/",
]
```

依序循環，可自由增減。

### 瀏覽行為

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `TAB_DURATION` | `40.0` 秒 | 每個分頁停留時間 |
| `SCROLL_INTERVAL` | `5.0` 秒 | 兩次滾動間隔，越大越省電 |
| `SCROLL_AMOUNT` | `700` px | 每次滾動距離 |
| `SCROLL_DURATION` | `2.8` 秒 | 滾動持續時間，越大越像真人操作 |

### OCR 識別

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `FRAME_SCALE` | `0.70` | 截圖縮放比例，越小越省 CPU；建議範圍 0.5–0.8 |
| `OCR_LANGUAGES` | `['en', 'ch_tra']` | `ch_tra` 為繁體中文，可加 `'ja'` 等 |
| `USE_GPU` | `False` | macOS 建議維持 False |

### 視覺效果

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `VISUAL_DURATION` | `4.5` 秒 | 綠框輪播動畫持續時間 |
| `VISUAL_REFRESH` | `0.32` 秒 | 輪播重新選框間隔 |
| `POST_OCR_DURATION` | `4.0` 秒 | OCR 完成後掃描動畫持續時間 |
| `POST_OCR_INTERVAL` | `0.55` 秒 | 掃描動畫每個框停留時間 |

### 視窗佈局

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `SCREEN_W` / `SCREEN_H` | `1792` / `1440` | 螢幕解析度，需與實際螢幕一致 |
| `p.TEXT_PANEL_FONT_SIZE` | `14` | 記錄面板字型大小，4K 螢幕建議 `28` |
| `p.CLOSE_BTN_SIZE` | `24` | 右上角關閉按鈕大小，4K 建議 `48` |

### Chrome 連線（`browser.py` 設定）

| 參數 | 說明 |
|------|------|
| `b.CHROME_DEBUG_USER_DATA` | Chrome 獨立 Profile 目錄，**必須改成你自己的路徑** |
| `b.CHROME_PROFILE_DIR` | Profile 名稱，預設 `"Default"` |
| `b.CHROME_DEBUG_PORT` | Remote Debugging 通訊埠，預設 `9222` |

### 內容區域過濾（`browser.py`）

`CONTENT_SELECTORS` 定義各網站主內容的 CSS selector，自動排除左右側欄只掃描貼文區域：

| 網站 | 使用的 selector |
|------|----------------|
| Facebook | `[role="main"]` |
| Instagram | `main[role="main"]` |
| Reddit | `shreddit-feed` |
| Yahoo | `#Col1-0-ContentCanvas` |

若網站改版後又掃到側欄，用 Chrome DevTools（F12）找到主內容元素，將新 selector 加入 `CONTENT_SELECTORS` 對應清單的最前面。

---

## 5. 效能優化建議

### 資源使用預估

| 模式 | CPU | 記憶體 |
|------|-----|--------|
| 預設 | 15–40% | ~600 MB |
| 長時間省電 | 8–20% | ~500 MB |

### 長時間執行（8–10 小時）省電設定

```python
SCROLL_INTERVAL   = 10.0
FRAME_SCALE       = 0.55
VISUAL_DURATION   = 3.0
VISUAL_REFRESH    = 0.80
p.PANEL_THROTTLE  = 0.50
```

### 高品質掃描設定

```python
SCROLL_INTERVAL   = 4.0
FRAME_SCALE       = 0.80
VISUAL_REFRESH    = 0.25
p.PANEL_THROTTLE  = 0.10
```

### 其他建議

- **減少 URLS 數量**：網站越少每輪越快，記憶體壓力越低
- **精簡 OCR 語言**：只保留需要的語言，每多一種就多一個模型
- **MacBook 長時間使用**：建議插電執行，`SCROLL_INTERVAL` 調到 12 秒以上

---

## 6. uv 套件管理

### 常用指令

```bash
uv sync                    # 安裝所有套件
uv add pynput psutil       # 新增選用套件
uv run chrome_ocr.py       # 執行程式
uv pip list                # 查看已安裝套件
uv sync --upgrade          # 更新所有套件
rm -rf .venv && uv sync    # 重建虛擬環境
```

### pyproject.toml 說明

```toml
[project]
requires-python = ">=3.12"   # Python 最低版本需求

dependencies = [
    "easyocr>=1.7.2",        # OCR 核心
    "opencv-python>=4.13",   # 影像處理
    "selenium>=4.43",        # 瀏覽器自動化
    "torch==2.2.2",          # Intel Mac 鎖定版本
    "torchvision==0.17.2",   # 配合 torch
    # 選用（uv add 安裝）：pynput、psutil、webdriver-manager
]
```

### ARM vs Intel torch 版本

| 架構 | 建議 |
|------|------|
| Intel Mac | `"torch==2.2.2"`（2.3+ 無 x86_64 wheel） |
| Apple Silicon | `"torch>=2.2"` |

---

## 關閉程式的方式

| 方式 | 說明 |
|------|------|
| 右上角 **✕** 按鈕 | 點擊記錄面板右上角 |
| **F12** | 全域快捷鍵，不需視窗焦點（需安裝 pynput） |
| **ESC** | 需要點擊視窗取得焦點後按 |
| **Ctrl+C** | 在 Terminal 中按 |

---

## 快速開始

```bash
# 1. clone 並安裝
git clone https://github.com/YiluYangYang/ShelvesProject_OCR.git
cd ShelvesProject_OCR
uv sync
uv add pynput psutil

# 2. 修改 chrome_ocr.py 中的路徑
# b.CHROME_DEBUG_USER_DATA = "/Users/<YOUR_USERNAME>/selenium-chrome"

# 3. 第一次執行，手動登入 FB / IG
uv run chrome_ocr.py

# 4. 之後每次直接執行
uv run chrome_ocr.py
```

---

*最後更新：2026-05-02*