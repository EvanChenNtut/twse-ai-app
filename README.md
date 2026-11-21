# 台股 AI 明日漲跌情報站（ML 自動訓練權重版 v5）

## v5 核心升級
1. **美股科技綜合連動（那指 + 費半 + TSM ADR）**：
   - 同時抓取那斯達克（`^IXIC` 45%）、費城半導體（`^SOX` 35%）與台積電 ADR（`TSM` 20%）最新收盤漲跌幅。
2. **機器學習自動訓練權重（Scikit-Learn LogisticRegression）**：
   - 每次排程執行時，會針對各檔標的過去 60～120 個交易日的四維度特徵與真實漲跌標籤進行訓練，自動學習並更新各因子的權重佔比（例如台積電自動提高美股科技權重至 37%），並將每日真實特徵樣本滾動存回 `market_data.json`。

## 更新你的 GitHub 倉庫步驟
1. 將 `twse_ai_auto_github_v5` 內的檔案（特別是 `.github/workflows/update_market.yml`、`scripts/fetch_and_predict.py`、`index.html`、`market_data.json`）上傳覆蓋至原本的 GitHub 倉庫。
2. 進入倉庫的 **Actions → Auto Update TWSE AI Market Data (ML v5)**，點擊 **Run workflow** 即可立即執行一次機器學習權重訓練與最新行情同步！
