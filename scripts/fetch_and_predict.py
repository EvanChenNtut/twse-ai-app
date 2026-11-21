import json
import math
import os
from datetime import datetime, timedelta
import numpy as np
import pytz
import requests
import yfinance as yf
import feedparser
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

TZ_TW = pytz.timezone("Asia/Taipei")
DATA_FILE = "market_data.json"

STOCK_CONFIGS = [
    {
        "code": "TAIEX",
        "name": "加權指數",
        "yf_symbol": "^TWII",
        "annual_vol": 0.24,
        "leverage": 1.0,
        "market_type": "TW",
    },
    {
        "code": "2330",
        "name": "台積電",
        "yf_symbol": "2330.TW",
        "annual_vol": 0.32,
        "leverage": 1.0,
        "market_type": "TW",
    },
    {
        "code": "0050",
        "name": "元大台灣50",
        "yf_symbol": "0050.TW",
        "annual_vol": 0.25,
        "leverage": 1.0,
        "market_type": "TW",
    },
    {
        "code": "00662",
        "name": "富邦NASDAQ",
        "yf_symbol": "00662.TW",
        "annual_vol": 0.29,
        "leverage": 1.0,
        "market_type": "US_TECH",
    },
    {
        "code": "00631L",
        "name": "元大台灣50正2",
        "yf_symbol": "00631L.TW",
        "annual_vol": 0.50,
        "leverage": 2.0,
        "market_type": "TW",
    },
    {
        "code": "00632R",
        "name": "元大台灣50反1",
        "yf_symbol": "00632R.TW",
        "annual_vol": 0.25,
        "leverage": -1.0,
        "market_type": "TW_INV",
    },
]


def get_next_trading_date(now_tw: datetime) -> datetime:
    target = now_tw.replace(hour=0, minute=0, second=0, microsecond=0)
    dow = target.weekday()
    closed = (now_tw.hour * 60 + now_tw.minute) >= (13 * 60 + 30)
    if dow == 5:
        target += timedelta(days=2)
    elif dow == 6:
        target += timedelta(days=1)
    elif dow == 4:
        if closed:
            target += timedelta(days=3)
    else:
        if closed:
            target += timedelta(days=1)
    return target


def fmt_signed_pct(val: float) -> str:
    return f"{'+' if val >= 0 else ''}{val:.2f}%"


def fetch_twse_foreign_flow():
    """抓取證交所三大法人買賣超金額（外資買賣超，單位：億元）"""
    try:
        url = "https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json"
        res = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        data = res.json()
        if data.get("stat") == "OK":
            for row in data.get("data", []):
                if "外資及陸資(不含外資自營商)" in row[0]:
                    net_val = float(row[3].replace(",", "")) / 1e8
                    return round(net_val, 2)
    except Exception as e:
        print("TWSE foreign flow fetch warning:", e)
    return None


def fetch_google_news_sentiment():
    """抓取 Google News 台股與美股科技即時新聞並計算情緒分數"""
    bull_words = ["大漲", "飆升", "創高", "利多", "買超", "優於預期", "護盤", "反彈", "回升", "成長", "突破", "強勢", "訂單", "止穩", "縮小", "降息"]
    bear_words = ["大跌", "重挫", "跌停", "利空", "賣超", "貶破", "恐慌", "破底", "下探", "裁員", "衰退", "拖累", "暴跌", "升息", "戰爭"]

    rss_url = "https://news.google.com/rss/search?q=台股+OR+外資+OR+台積電+OR+費半+OR+那斯達克&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    feed = feedparser.parse(rss_url)
    items = []
    total_impact = 0

    for idx, entry in enumerate(feed.entries[:10]):
        title = entry.title.split(" - ")[0]
        source = entry.title.split(" - ")[1] if " - " in entry.title else "即時財經"
        score = 0
        for w in bull_words:
            if w in title:
                score += 4
        for w in bear_words:
            if w in title:
                score -= 4
        score = max(-10, min(10, score))
        sentiment = "bull" if score > 0 else ("bear" if score < 0 else "neutral")
        total_impact += score
        items.append({
            "id": f"news-{idx}",
            "source": source,
            "category": "即時新聞",
            "time": "今日更新",
            "title": title,
            "link": entry.link,
            "sentiment": sentiment,
            "impact": score,
        })

    news_score = max(15, min(85, round(50 + total_impact * 1.2)))
    return items, news_score


def fetch_us_tech_composite():
    """抓取那斯達克 (^IXIC)、費城半導體 (^SOX)、台積電 ADR (TSM) 並計算綜合分數與歷史日報酬序列"""
    symbols = {"IXIC": "^IXIC", "SOX": "^SOX", "TSM": "TSM"}
    series_pct = {}
    latest_pct = {"IXIC": 0.0, "SOX": 0.0, "TSM": 0.0}

    for key, sym in symbols.items():
        try:
            df = yf.Ticker(sym).history(period="90d")
            if not df.empty and len(df) >= 2:
                pct_s = df["Close"].pct_change().dropna() * 100.0
                pct_s.index = pct_s.index.strftime("%Y-%m-%d")
                series_pct[key] = pct_s
                latest_pct[key] = round(float(pct_s.iloc[-1]), 2)
        except Exception as e:
            print(f"{sym} fetch warning:", e)

    # 加權綜合美股科技動能：45% 那斯達克 + 35% 費城半導體 + 20% 台積電 ADR
    comp_pct = (
        latest_pct["IXIC"] * 0.45
        + latest_pct["SOX"] * 0.35
        + latest_pct["TSM"] * 0.20
    )
    us_score = max(15, min(85, round(50 + comp_pct * 11)))
    return us_score, round(comp_pct, 2), latest_pct, series_pct


def train_ml_weights(X_rows, y_rows, default_weights):
    """
    使用 L2 正則化邏輯斯迴歸 (LogisticRegression) 自動訓練四維度特徵權重：
    features = [f_score, u_score, n_score, t_score] (皆標準化至 -1 ~ +1)
    回傳自動學習後的百分比權重 [w1, w2, w3, w4] (總和 100%) 與預測機率函數
    """
    if len(X_rows) < 20 or len(set(y_rows)) < 2:
        return default_weights, None, None, "初始暖機期 (樣本累積中)"

    X = np.array(X_rows, dtype=float)
    y = np.array(y_rows, dtype=int)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # 較強正則化 C=0.35 避免小樣本過擬合
    clf = LogisticRegression(C=0.35, max_iter=500, random_state=42)
    clf.fit(X_scaled, y)

    # 取係數絕對值並結合先驗平滑，轉換為直觀的百分比權重 (總和 100%)
    raw_abs = np.abs(clf.coef_[0])
    # 與先驗權重做 70% ML 學習 + 30% 穩健先驗融合，防止單一特徵極端化
    prior = np.array(default_weights, dtype=float) / 100.0
    if raw_abs.sum() > 1e-6:
        learned = raw_abs / raw_abs.sum()
        blended = 0.70 * learned + 0.30 * prior
    else:
        blended = prior

    # 設定最低權重下限 8%，確保四個維度皆有代表性
    blended = np.maximum(blended, 0.08)
    blended = blended / blended.sum()

    int_weights = [int(round(w * 100)) for w in blended]
    diff = 100 - sum(int_weights)
    int_weights[int(np.argmax(blended))] += diff

    return int_weights, clf, scaler, f"ML 自動訓練完成 ({len(X_rows)} 日樣本)"


def main():
    now_tw = datetime.now(TZ_TW)
    today_str = now_tw.strftime("%Y-%m-%d")
    target_dt = get_next_trading_date(now_tw)
    target_key = target_dt.strftime("%Y-%m-%d")
    target_short = target_dt.strftime("%m/%d")

    existing_data = {"stocks": {}, "pending_predictions": {}, "training_samples": {}}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except Exception:
            pass

    foreign_net_billion = fetch_twse_foreign_flow()
    news_items, news_score = fetch_google_news_sentiment()
    us_score, us_comp_pct, us_latest_pct, us_series_pct = fetch_us_tech_composite()

    if foreign_net_billion is not None:
        foreign_score = max(15, min(85, round(50 + foreign_net_billion * 0.12)))
        foreign_desc = f"外資今日{'買超' if foreign_net_billion >= 0 else '賣超'} {abs(foreign_net_billion):.1f} 億元"
    else:
        foreign_score = 42
        foreign_desc = "外資現貨籌碼中性偏保守，觀察期貨淨部位"

    pending_all = existing_data.get("pending_predictions", {})
    training_all = existing_data.get("training_samples", {})
    stocks_output = {}

    for cfg in STOCK_CONFIGS:
        code = cfg["code"]
        lev = cfg["leverage"]
        ticker = yf.Ticker(cfg["yf_symbol"])
        hist_df = ticker.history(period="95d")

        if hist_df.empty or len(hist_df) < 35:
            continue

        last_close = float(hist_df["Close"].iloc[-1])
        prev_close = float(hist_df["Close"].iloc[-2])
        change_val = last_close - prev_close
        change_pct = (change_val / prev_close) * 100
        last_trade_dt = hist_df.index[-1].to_pydatetime()
        last_trade_key = last_trade_dt.strftime("%Y-%m-%d")
        last_trade_short = last_trade_dt.strftime("%m/%d")

        ma20 = float(hist_df["Close"].tail(20).mean())
        bias_ma20 = ((last_close - ma20) / ma20) * 100
        raw_tech_score = max(15, min(85, round(50 + bias_ma20 * 4)))

        us_detail_str = (
            f"那指 {fmt_signed_pct(us_latest_pct['IXIC'])} / "
            f"費半 {fmt_signed_pct(us_latest_pct['SOX'])} / "
            f"TSM ADR {fmt_signed_pct(us_latest_pct['TSM'])}"
        )

        if lev < 0:
            f_score = 100 - foreign_score
            u_score = 100 - us_score
            n_score = 100 - news_score
            t_score = raw_tech_score
            f_desc = f"反向避險連動：{foreign_desc}（有利反1表現）"
            u_desc = f"反向美股連動：{us_detail_str}"
            n_desc = "市場避險情緒升溫時有利反向 ETF 走勢"
            t_desc = f"距 20 日均線乖離 {fmt_signed_pct(bias_ma20)}"
        elif cfg["market_type"] == "US_TECH":
            f_score = round(foreign_score * 0.35 + us_score * 0.65)
            u_score = us_score
            n_score = news_score
            t_score = raw_tech_score
            f_desc = f"美股科技資金連動（綜合美股動能 {fmt_signed_pct(us_comp_pct)}）"
            u_desc = us_detail_str
            n_desc = "AI 與半導體財報及利率預期主導短線情緒"
            t_desc = f"距 20 日均線乖離 {fmt_signed_pct(bias_ma20)}"
        else:
            f_score = foreign_score
            u_score = us_score
            n_score = news_score
            t_score = raw_tech_score
            f_desc = foreign_desc
            u_desc = us_detail_str
            n_desc = "即時彙整 Google 財經新聞與市場多空關鍵字"
            t_desc = f"收盤價距 20 日均線乖離 {fmt_signed_pct(bias_ma20)}"

        # 建構過去 60 個交易日的歷史特徵矩陣 X 與真實漲跌標籤 y 供機器學習自動訓練權重
        stock_samples = training_all.get(code, [])
        if len(stock_samples) < 40 and len(hist_df) >= 65:
            stock_samples = []
            closes = hist_df["Close"].values
            dates_idx = hist_df.index
            for i in range(21, len(closes) - 1):
                d_key = dates_idx[i].strftime("%Y-%m-%d")
                prev_d_key = dates_idx[i - 1].strftime("%Y-%m-%d")

                # 當日盤前已知之四維度歷史特徵近似值
                mom_1d = ((closes[i] - closes[i - 1]) / closes[i - 1]) * 100
                mom_3d = ((closes[i] - closes[i - 3]) / closes[i - 3]) * 100
                ma20_i = float(np.mean(closes[i - 19 : i + 1]))
                bias_i = ((closes[i] - ma20_i) / ma20_i) * 100

                ixic_p = float(us_series_pct.get("IXIC", {}).get(prev_d_key, 0.0))
                sox_p = float(us_series_pct.get("SOX", {}).get(prev_d_key, 0.0))
                tsm_p = float(us_series_pct.get("TSM", {}).get(prev_d_key, 0.0))
                us_hist_pct = ixic_p * 0.45 + sox_p * 0.35 + tsm_p * 0.20

                hist_f = max(15, min(85, 50 + mom_1d * 8))
                hist_u = max(15, min(85, 50 + us_hist_pct * 11))
                hist_n = max(15, min(85, 50 + mom_3d * 4))
                hist_t = max(15, min(85, 50 + bias_i * 4))

                if lev < 0:
                    hist_f, hist_u, hist_n = 100 - hist_f, 100 - hist_u, 100 - hist_n

                next_ret = ((closes[i + 1] - closes[i]) / closes[i]) * 100
                y_label = 1 if next_ret >= 0 else 0

                stock_samples.append({
                    "date": d_key,
                    "features": [round(hist_f, 1), round(hist_u, 1), round(hist_n, 1), round(hist_t, 1)],
                    "y": y_label,
                })

        # 若有剛結算的真實當日四因子快照，加入真實訓練樣本池（滾動保留最近 120 個交易日）
        stock_pending = pending_all.get(code, {})
        if last_trade_key in stock_pending:
            snap = stock_pending[last_trade_key]
            y_actual = 1 if change_pct >= 0 else 0
            if "features" in snap and not any(s["date"] == last_trade_key for s in stock_samples):
                stock_samples.append({
                    "date": last_trade_key,
                    "features": snap["features"],
                    "y": y_actual,
                })

        stock_samples = stock_samples[-120:]
        training_all[code] = stock_samples

        # 執行機器學習自動權重訓練
        X_train = [s["features"] for s in stock_samples]
        y_train = [s["y"] for s in stock_samples]
        learned_weights, clf, scaler, ml_status = train_ml_weights(
            X_train, y_train, [35, 30, 20, 15]
        )

        w_f, w_u, w_n, w_t = learned_weights
        current_features = [f_score, u_score, n_score, t_score]

        # 結合 ML 機率與自動學習權重加權分數，得出穩定看漲機率
        weighted_score = (
            f_score * (w_f / 100.0)
            + u_score * (w_u / 100.0)
            + n_score * (w_n / 100.0)
            + t_score * (w_t / 100.0)
        )
        if clf is not None and scaler is not None:
            ml_prob = float(clf.predict_proba(scaler.transform([current_features]))[0][1]) * 100.0
            # 60% 採用 ML 模型推論機率 + 40% 採用動態學習權重加權分數，兼顧敏感度與穩定性
            blended_prob = 0.60 * ml_prob + 0.40 * weighted_score
        else:
            blended_prob = weighted_score

        base_bull_prob = max(12, min(88, round(blended_prob)))

        factors = [
            {"name": "外資與法人資金動能", "score": f_score, "weight": f"{w_f}%", "desc": f_desc},
            {"name": "美股科技綜合連動 (那指/費半/TSM)", "score": u_score, "weight": f"{w_u}%", "desc": u_desc},
            {"name": "網路新聞與社群情緒", "score": n_score, "weight": f"{w_n}%", "desc": n_desc},
            {"name": "技術面均線乖離率", "score": t_score, "weight": f"{w_t}%", "desc": t_desc},
        ]

        daily_vol_pct = (cfg["annual_vol"] / math.sqrt(252)) * 100
        bias = (base_bull_prob - 50) / 50.0
        pred_move_pct = round(bias * daily_vol_pct * 1.15, 2)
        pred_dir = "漲" if base_bull_prob >= 50 else "跌"
        pred_prob = base_bull_prob if base_bull_prob >= 50 else (100 - base_bull_prob)

        # 讀取或初始化近 30 個交易日回測清單
        prev_stock = existing_data.get("stocks", {}).get(code, {})
        history_list = list(prev_stock.get("history", []))

        if len(history_list) < 30 and len(hist_df) >= 31:
            history_list = []
            sub_df = hist_df.tail(31)
            for i in range(1, len(sub_df)):
                c_today = float(sub_df["Close"].iloc[i])
                c_yest = float(sub_df["Close"].iloc[i - 1])
                d_str = sub_df.index[i].strftime("%m/%d")
                act_pct = ((c_today - c_yest) / c_yest) * 100
                act_dir = "漲" if act_pct >= 0 else "跌"

                # 使用對應歷史樣本的特徵與當前 ML 權重計算回測
                sample_idx = len(stock_samples) - (len(sub_df) - i)
                if 0 <= sample_idx < len(stock_samples):
                    sf = stock_samples[sample_idx]["features"]
                    est_prob = round(
                        sf[0] * (w_f / 100.0)
                        + sf[1] * (w_u / 100.0)
                        + sf[2] * (w_n / 100.0)
                        + sf[3] * (w_t / 100.0)
                    )
                else:
                    est_prob = 50
                est_prob = max(25, min(78, est_prob))
                p_dir = "漲" if est_prob >= 50 else "跌"
                p_val = est_prob if est_prob >= 50 else (100 - est_prob)
                p_pct = round(((est_prob - 50) / 50.0) * daily_vol_pct * 1.15, 2)

                history_list.append({
                    "date": d_str,
                    "pred": f"{p_dir} {p_val}%",
                    "predPct": fmt_signed_pct(p_pct),
                    "actual": act_dir,
                    "actualPct": fmt_signed_pct(act_pct),
                    "hit": p_dir == act_dir,
                })

        # 結算已鎖定的預測快照
        if last_trade_key in stock_pending:
            snap = stock_pending.pop(last_trade_key)
            act_dir = "漲" if change_pct >= 0 else "跌"
            new_entry = {
                "date": last_trade_short,
                "pred": snap["pred"],
                "predPct": snap["predPct"],
                "actual": act_dir,
                "actualPct": fmt_signed_pct(change_pct),
                "hit": snap["predDir"] == act_dir,
                "autoLogged": True,
            }
            existing_idx = next((idx for idx, x in enumerate(history_list) if x["date"] == last_trade_short), -1)
            if existing_idx >= 0:
                history_list[existing_idx] = new_entry
            else:
                history_list.append(new_entry)

        history_list = history_list[-30:]

        # 寫入下一個交易日的預測快照（含四維度特徵向量供未來 ML 再訓練）
        stock_pending[target_key] = {
            "predDir": pred_dir,
            "pred": f"{pred_dir} {pred_prob}%",
            "predPct": fmt_signed_pct(pred_move_pct),
            "features": current_features,
        }
        pending_all[code] = stock_pending

        stocks_output[code] = {
            "code": code,
            "name": cfg["name"],
            "yfSymbol": cfg["yf_symbol"],
            "annualVol": cfg["annual_vol"],
            "leverage": cfg["leverage"],
            "price": f"{last_close:,.2f}",
            "change": f"{'+' if change_val >= 0 else ''}{change_val:,.2f}",
            "changePct": fmt_signed_pct(change_pct),
            "isUp": change_val >= 0,
            "baseBullProb": base_bull_prob,
            "mlStatus": ml_status,
            "learnedWeights": {
                "foreign": w_f,
                "usTech": w_u,
                "news": w_n,
                "tech": w_t,
            },
            "factors": factors,
            "history": history_list,
        }

    output_payload = {
        "updatedAt": now_tw.strftime("%Y/%m/%d %H:%M"),
        "todayDate": today_str,
        "targetDate": target_key,
        "foreignNetBillion": foreign_net_billion,
        "usTechPct": us_latest_pct,
        "news": news_items,
        "stocks": stocks_output,
        "pending_predictions": pending_all,
        "training_samples": training_all,
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=2)
    print(f"Successfully updated {DATA_FILE} with ML weights at {output_payload['updatedAt']}")


if __name__ == "__main__":
    main()
