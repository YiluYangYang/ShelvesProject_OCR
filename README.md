# Chrome OCR 偵測系統

自動瀏覽社群網站（Facebook、Instagram、Threads、Reddit 等），即時截圖並用 EasyOCR 識別畫面中的文字，將結果顯示於右側面板。

---

## 目錄

1. [環境準備與安裝](#1-環境準備與安裝)
2. [Chrome Profile 初始設定](#2-chrome-profile-初始設定)
3. [可調整參數說明](#3-可調整參數說明)
4. [效能優化建議](#4-效能優化建議)
5. [uv 套件管理](#5-uv-套件管理)

---

## 1. 環境準備與安裝

### 系統需求

| 項目 | 最低需求 |
|------|---------|
| macOS | 13 Ventura 以上 |
| Python | 3.12 以上 |
| Google Chrome | 任意近期版本 |
| 記憶體 | 8 GB（建議 16 GB） |

---

### Mac ARM（Apple Silicon）

> M1 / M2 / M3 / M4 系列

**步驟 1：安裝 uv**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.zshrc
```

**步驟 2：clone 專案並建立虛擬環境**

```bash
git clone <your-repo-url>
cd ShelvesProject_OCR
uv sync
```

**步驟 3：安裝選用套件**

```bash
uv add pynput   # 全域快捷鍵（F12 關閉程式）
uv add psutil   # 效能監控（標題列顯示 CPU / 記憶體）
```

**ARM 特別注意事項**

uv 會自動抓 ARM 版的 PyTorch wheel，不需手動指定。若安裝時遇到 `torch` 版本衝突：

```bash
uv add "torch>=2.2" "torchvision>=0.17"
```

EasyOCR 在 ARM 上建議維持 `USE_GPU = False`（MPS 支援尚不穩定）。

---

### Mac Intel（x86_64）

> 2020 年以前的 Intel MacBook / iMac / Mac mini

**步驟 1：安裝 uv**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.zshrc
```

**步驟 2：clone 專案並建立虛擬環境**

```bash
git clone <your-repo-url>
cd ShelvesProject_OCR
uv sync
```

**步驟 3：安裝選用套件**

```bash
uv add pynput psutil
```

**Intel 特別注意事項**

Intel Mac 的 PyTorch 最高支援 `torch 2.2.x`，`pyproject.toml` 已鎖定此版本，直接 `uv sync` 即可。

若系統已安裝 Anaconda，務必確認使用 uv 的虛擬環境，避免 Anaconda Tk 版本不相容導致程式 crash：

```bash
# 應顯示 .venv/bin/python，而非 /opt/anaconda3/...
which python
```

---

### 驗證安裝

```bash
uv run python -c "import easyocr, cv2, selenium, tkinter; print('✓ 所有核心套件正常')"
```

---

## 2. Chrome Profile 初始設定

### 原理說明

程式使用 **Chrome Remote Debugging** 模式啟動一個獨立的 Chrome 實例，資料存放於 `/Users/<你的帳號>/selenium-chrome`，與平常使用的 Chrome 完全隔離。第一次需要手動登入，之後登入狀態會永久保留。

---

### 初次登入流程（只需做一次）

**步驟 1：修改設定檔路徑**

開啟 `chrome_ocr.py`，找到以下這行並將 `yilu` 換成你的 macOS 使用者名稱：

```python
CHROME_DEBUG_USER_DATA = "/Users/yilu/selenium-chrome"
```

查詢你的使用者名稱：

```bash
whoami
```

**步驟 2：第一次啟動程式**

```bash
uv run chrome_ocr.py
```

程式會自動開啟一個新的 Chrome 視窗。

**步驟 3：手動登入各網站**

在彈出的 Chrome 視窗中依序登入：

- Facebook：`https://www.facebook.com`
- Instagram：`https://www.instagram.com`
- Threads：隨 Instagram 帳號登入，通常不需額外操作

**步驟 4：驗證登入狀態**

按右上角 ✕ 或 Ctrl+C 結束，再重新執行：

```bash
uv run chrome_ocr.py
```

若 Facebook / Instagram 不需重新登入，代表設定成功。

---

### 環境測試

**測試 Chrome Remote Debugging 連線與截圖：**

```bash
uv run python - <<'EOF'
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import socket, subprocess, time

PORT     = 9222
CHROME   = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DATA_DIR = "/Users/yilu/selenium-chrome"  # 改成你的路徑

def port_open():
    s = socket.socket()
    r = s.connect_ex(("127.0.0.1", PORT)) == 0
    s.close()
    return r

if not port_open():
    subprocess.Popen([CHROME, f"--remote-debugging-port={PORT}", f"--user-data-dir={DATA_DIR}"])
    for _ in range(20):
        time.sleep(0.5)
        if port_open():
            break

opts = Options()
opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{PORT}")
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
driver.get("https://www.google.com")
driver.save_screenshot("/tmp/test_screenshot.png")
print(f"✓ 截圖成功，頁面標題：{driver.title}")
print("  截圖存至 /tmp/test_screenshot.png")
EOF
```

**測試 EasyOCR 初始化：**

```bash
uv run python - <<'EOF'
import easyocr, numpy as np
reader = easyocr.Reader(['en', 'ch_tra'], gpu=False)
img = np.ones((50, 200, 3), dtype=np.uint8) * 255
reader.readtext(img, detail=0)
print("✓ EasyOCR 初始化成功")
EOF
```

---

## 3. 可調整參數說明

所有參數集中在 `chrome_ocr.py` 開頭的「可調整參數」區塊。

### 網頁與瀏覽行為

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `URLS` | 5 個網址 | 要巡覽的網站清單，依序輪流，可自由增減 |
| `TAB_DURATION` | `40.0` 秒 | 每個分頁停留時間，時間到自動切換下一個 |
| `SCROLL_INTERVAL` | `8.0` 秒 | 兩次滾動之間的等待時間，越大越省電 |
| `SCROLL_AMOUNT` | `700` px | 每次滾動距離（CSS pixel） |
| `SCROLL_DURATION` | `2.8` 秒 | 一次滾動動作持續時間，越大越像真人操作 |

### OCR 識別

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `FRAME_SCALE` | `0.55` | 截圖縮放比例，越小越省 CPU；建議範圍 0.5–0.8 |
| `OCR_LANGUAGES` | `['en', 'ch_tra']` | OCR 語言，`ch_tra` 為繁體中文，可加 `'ja'` 等 |
| `USE_GPU` | `False` | 是否使用 GPU，macOS 建議維持 False |
| `SHOW_ALL_DETECTED` | `False` | True 時在 Overlay 顯示所有偵測框（藍色），方便除錯 |

### 視覺效果

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `VISUAL_DURATION` | `4.5` 秒 | 綠框輪播動畫持續時間 |
| `VISUAL_REFRESH` | `0.50` 秒 | 輪播期間重新選框的間隔，越小越活潑但越耗電 |
| `POST_OCR_DURATION` | `4.0` 秒 | OCR 完成後掃描動畫持續時間 |
| `POST_OCR_INTERVAL` | `0.55` 秒 | 掃描動畫每個框停留時間（段落 > 3 時） |

### 視窗佈局

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `SCREEN_W` / `SCREEN_H` | `1792` / `1440` | 螢幕解析度，需與實際螢幕一致。4K 無縮放請改 `3840` / `2160` |
| `TEXT_PANEL_FONT_SIZE` | `14` | 右側面板字型大小，4K 螢幕建議改 `28` |
| `CLOSE_BTN_SIZE` | `24` | 右上角關閉按鈕大小（px），4K 建議改 `48` |

### Chrome 連線設定

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `CHROME_APP` | `/Applications/Google Chrome.app/...` | Chrome 執行檔路徑，通常不需修改 |
| `CHROME_DEBUG_PORT` | `9222` | Remote Debugging 通訊埠，被佔用時可改 `9333` 等 |
| `CHROME_DEBUG_USER_DATA` | `/Users/yilu/selenium-chrome` | **必須改成你自己帳號的路徑** |

### 內容區域過濾

`CONTENT_SELECTORS` 字典定義各網站的主內容 CSS selector，程式自動排除左右側欄，只掃描貼文區域。若某網站改版後又掃到選單，可用 Chrome DevTools（F12）找到主內容元素，將新 selector 加到對應清單的最前面：

```python
CONTENT_SELECTORS = {
    "facebook.com": [
        '[role="main"]',        # 優先使用第一個
        "#content_container",
    ],
    # 其他網站...
}
```

---

## 4. 效能優化建議

### 資源使用預估

| 模式 | CPU | 記憶體 | 適用情境 |
|------|-----|--------|---------|
| 目前預設（省電） | 10–30% | ~600 MB | 長時間背景執行（8–10 小時） |
| 高品質模式 | 30–70% | ~800 MB | 短時間精準掃描 |

### 長時間執行的省電設定

```python
SCROLL_INTERVAL  = 10.0   # 拉長滾動間隔
FRAME_SCALE      = 0.50   # 縮小截圖（犧牲少量準確率）
VISUAL_DURATION  = 3.0    # 縮短動畫
VISUAL_REFRESH   = 0.80   # 降低輪播頻率
PANEL_THROTTLE   = 0.50   # 降低面板更新頻率
```

### 高品質掃描設定

```python
SCROLL_INTERVAL  = 5.0
FRAME_SCALE      = 0.75
VISUAL_REFRESH   = 0.32
PANEL_THROTTLE   = 0.10
```

### 其他優化方向

**減少目標網站：** `URLS` 清單越少，每輪循環越快，記憶體壓力越低。

**精簡 OCR 語言：** 每多一個語言就多載入一個模型，只保留需要的語言可明顯加速。

```python
OCR_LANGUAGES = ['ch_tra']         # 只要繁體中文
OCR_LANGUAGES = ['en', 'ch_tra']   # 英文 + 繁體中文（預設）
```

**MacBook 長時間使用：** 插電執行可避免電池循環耗損。Intel MacBook 建議將 `SCROLL_INTERVAL` 調到 12–15 秒，避免風扇長時間高速運轉。

---

## 5. uv 套件管理

### 常用指令速查

```bash
# 安裝 / 同步所有套件
uv sync

# 新增套件（會自動更新 pyproject.toml）
uv add pynput
uv add psutil

# 移除套件
uv remove pynput

# 執行程式（自動使用 .venv，不需手動 activate）
uv run chrome_ocr.py

# 查看已安裝套件
uv pip list

# 更新所有套件至最新版
uv sync --upgrade

# 重建虛擬環境（遇到奇怪錯誤時）
rm -rf .venv && uv sync
```

### pyproject.toml 結構說明

```toml
[project]
name = "chrome-test"
version = "0.1.0"
requires-python = ">=3.12"

dependencies = [
    "easyocr>=1.7.2",        # OCR 核心
    "opencv-python>=4.13",   # 影像處理
    "selenium>=4.43",        # 瀏覽器自動化
    "torch==2.2.2",          # Intel Mac 鎖定此版本
    "torchvision==0.17.2",   # 配合 torch 版本
    # 建議額外 uv add：pynput、psutil、webdriver-manager
]
```

### ARM vs Intel 的 torch 版本差異

| 架構 | 建議寫法 | 原因 |
|------|---------|------|
| Intel Mac | `"torch==2.2.2"` | 2.3+ 不提供 macOS x86_64 wheel |
| Apple Silicon | `"torch>=2.2"` | 可使用更新版本 |

若要讓同一份設定在兩種架構都能運作：

```toml
"torch>=2.2,<2.3; platform_machine == 'x86_64'",
"torch>=2.2;       platform_machine == 'arm64'",
```

### 建議的 .gitignore

```gitignore
.venv/
__pycache__/
*.pyc
*.pyo
uv.lock
selenium-chrome/
```

> `uv.lock` 若用於團隊協作建議 commit，個人專案可加入 `.gitignore`。

---

## 快速開始

```bash
# 1. clone 並安裝
git clone <your-repo-url>
cd ShelvesProject_OCR
uv sync
uv add pynput psutil

# 2. 修改 chrome_ocr.py 中的路徑（搜尋 CHROME_DEBUG_USER_DATA）
# CHROME_DEBUG_USER_DATA = "/Users/<你的帳號>/selenium-chrome"

# 3. 第一次執行，手動登入 FB / IG
uv run chrome_ocr.py

# 4. 之後每次直接執行
uv run chrome_ocr.py
```

---

*最後更新：2026-04-21*
