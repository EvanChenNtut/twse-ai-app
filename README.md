# 台股 AI 明日漲跌情報站（全自動真實數據版 v4）

## 追蹤標的清單
- **加權指數（TAIEX）**
- **台積電（2330）**
- **元大台灣50（0050）**
- **富邦NASDAQ（00662）**（追蹤美國那斯達克 100 指數連動）
- **元大台灣50正2（00631L）**（2X 槓桿波動率與幅度模型）
- **元大台灣50反1（00632R）**（內建反向 ETF 邏輯：大盤與外資偏空時自動調升反1看漲機率）

## 100% 免費全自動部署教學（GitHub Pages + GitHub Actions）
1. 在 GitHub 建立一個新的公開倉庫（Public Repository，例如 `twse-ai-app`）。
2. 將 `twse_ai_auto_github_v4` 資料夾內的**所有檔案（包含隱藏資料夾 `.github`、`scripts`、`icons`、`index.html`、`market_data.json`、`manifest.json`、`sw.js`）**上傳到該倉庫根目錄。
3. 开启自動排程權限：進入倉庫的 **Settings → Actions → General → Workflow permissions**，勾選 **Read and write permissions** 並按 Save。
4. 开启免費網址：進入倉庫的 **Settings → Pages**，在 **Source** 選擇 `Deploy from a branch`，Branch 選擇 `main` / `/ (root)` 並按 Save，約 1 分鐘後上方就會出現你的專屬網址（`https://你的帳號.github.io/twse-ai-app/`）。
5. 每天週一至週五 **14:30**，GitHub Actions 會自動執行 `scripts/fetch_and_predict.py` 抓取真實收盤價、證交所外資買賣超與 Google 新聞並自動結算近 30 個交易日回測！
