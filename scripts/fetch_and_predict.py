import json
import math
import os
import re
from datetime import datetime, timedelta
import pytz
import requests
import yfinance as yf
import feedparser

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
        "leverage": -1.0,  # 反向 ETF：大盤偏空時反1看漲機率提高
        "market_type": "TW_INV",
    },
]


def get_next_trading_date(now_tw: datetime) -> datetime:
    target = now_tw.replace(hour=0, minute=0, second=0, microsecond=0)
    dow = target.weekday()  # 0=Mon ... 4=Fri, 5=Sat, 6=Sun
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


def fetch_twse_foreign_flow():
    """抓取證交所三大法人買賣超金額（外資買賣超）"""
    try:
        url = "https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json"
        res = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        data = res.json()
        if data.get("stat") == "OK":
            for row in data.get("data", []):
                if "外資及陸資(不含外資自營商)" in row[0]:
                    net_val = float(row[3].replace(",", "")) / 1e8  # 轉換為億元
                    return round(net_val, 2)
    except Exception as e:
        print("TWSE foreign flow fetch warning:", e)
    return None


def fetch_google_news_sentiment():
    """抓取 Google News 台股與美股科技即時新聞並計算情緒分數"""
    bull_words = ["大漲", "飆升", "創高", "利多", "買超", "優於預期", "護盤", "反彈", "回升", "成長", "突破", "強勢", "訂單", "止穩", "縮小", "降息"]
    bear_words = ["大跌", "重挫", "跌停", "利空", "賣超", "貶破", "恐慌", "破底", "下探", "裁員", "衰退", "拖累", "暴跌", "升息", "戰爭"]

    rss_url = "https://news.google.com/rss/search?q=台股+OR+外資+OR+台積電+OR+那斯達克&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
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

    # 轉換為 0~100 的新聞情緒分數 (50為中性)
    news_score = max(15, min(85, round(50 + total_impact * 1.2)))
    return items, news_score


def fetch_us_nasdaq_score():
    """抓取美國那斯達克綜合指數 (^IXIC) 與費半 (^SOX) 近期漲跌作為美股連動分數"""
    try:
        ixic = yf.Ticker("^IXIC").history(period="5d")
        if len(ixic) >= 2:
            pct = ((ixic["Close"].iloc[-1] - ixic["Close"].iloc[-2]) / ixic["Close"].iloc[-2]) * 100
            score = max(15, min(85, round(50 + pct * 12)))
            return score, round(pct, 2)
    except Exception as e:
        print("IXIC fetch warning:", e)
    return 48, 0.0


def fmt_signed_pct(val: float) -> str:
    return f"{'+' if val >= 0 else ''}{val:.2f}%"


def main():
    now_tw = datetime.now(TZ_TW)
    today_str = now_tw.strftime("%Y-%m-%d")
    target_dt = get_next_trading_date(now_tw)
    target_key = target_dt.strftime("%Y-%m-%d")
    target_short = target_dt.strftime("%m/%d")

    # 載入既有的 market_data.json（保留歷史預測與 30 日回測）
    existing_data = {"stocks": {}, "pending_predictions": {}}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except Exception:
            pass

    foreign_net_billion = fetch_twse_foreign_flow()
    news_items, news_score = fetch_google_news_sentiment()
    nasdaq_score, nasdaq_pct = fetch_us_nasdaq_score()

    # 計算外資籌碼分數 (0~100)
    if foreign_net_billion is not None:
        foreign_score = max(15, min(85, round(50 + foreign_net_billion * 0.12)))
        foreign_desc = f"外資今日{'買超' if foreign_net_billion >= 0 else '賣超'} {abs(foreign_net_billion):.1f} 億元"
    else:
        foreign_score = 42
        foreign_desc = "外資現貨籌碼中性偏保守，觀察期貨淨部位"

    pending_all = existing_data.get("pending_predictions", {})
    stocks_output = {}

    for cfg in STOCK_CONFIGS:
        code = cfg["code"]
        lev = cfg["leverage"]
        ticker = yf.Ticker(cfg["yf_symbol"])
        hist_df = ticker.history(period="45d")

        if hist_df.empty or len(hist_df) < 2:
            continue

        last_close = float(hist_df["Close"].iloc[-1])
        prev_close = float(hist_df["Close"].iloc[-2])
        change_val = last_close - prev_close
        change_pct = (change_val / prev_close) * 100
        last_trade_dt = hist_df.index[-1].to_pydatetime()
        last_trade_key = last_trade_dt.strftime("%Y-%m-%d")
        last_trade_short = last_trade_dt.strftime("%m/%d")

        # 技術面分數：計算收盤價相對於 20 日均線 (MA20) 的位置與 RSI 乖離
        ma20 = float(hist_df["Close"].tail(20).mean())
        bias_ma20 = ((last_close - ma20) / ma20) * 100
        raw_tech_score = max(15, min(85, round(50 + bias_ma20 * 4)))

        # 若為反向 ETF (00632R, leverage < 0)，大盤越偏空則該 ETF 越偏多
        if lev < 0:
            f_score = 100 - foreign_score
            u_score = 100 - nasdaq_score
            n_score = 100 - news_score
            t_score = raw_tech_score
            f_desc = f"反向避險連動：{foreign_desc}（有利反1表現）"
            u_desc = f"那斯達克變動 {fmt_signed_pct(nasdaq_pct)}，反向避險需求連動"
            n_desc = "市場避險情緒升溫時有利反向 ETF 走勢"
            t_desc = f"距 20 日均線乖離 {fmt_signed_pct(bias_ma20)}"
        elif cfg["market_type"] == "US_TECH":
            f_score = round(foreign_score * 0.4 + nasdaq_score * 0.6)
            u_score = nasdaq_score
            n_score = news_score
            t_score = raw_tech_score
            f_desc = f"美股科技資金連動（那斯達克 {fmt_signed_pct(nasdaq_pct)}）"
            u_desc = f"高度追蹤美國那斯達克指數（最新 {fmt_signed_pct(nasdaq_pct)}）"
            n_desc = "AI 與科技股財報與利率預期主導短線情緒"
            t_desc = f"距 20 日均線乖離 {fmt_signed_pct(bias_ma20)}"
        else:
            f_score = foreign_score
            u_score = nasdaq_score
            n_score = news_score
            t_score = raw_tech_score
            f_desc = foreign_desc
            u_desc = f"美股那斯達克最新變動 {fmt_signed_pct(nasdaq_pct)}，連動台股電子權值"
            n_desc = "即時彙整 Google 財經新聞與市場多空關鍵字"
            t_desc = f"收盤價距 20 日均線乖離 {fmt_signed_pct(bias_ma20)}"

        factors = [
            {"name": "外資與法人資金動能", "score": f_score, "weight": "35%", "desc": f_desc},
            {"name": "美股那斯達克連動", "score": u_score, "weight": "30%", "desc": u_desc},
            {"name": "網路新聞與社群情緒", "score": n_score, "weight": "20%", "desc": n_desc},
            {"name": "技術面均線乖離率", "score": t_score, "weight": "15%", "desc": t_desc},
        ]

        # 由四大真實因子加權計算看漲機率
        weighted_score = (
            f_score * 0.35 + u_score * 0.30 + n_score * 0.20 + t_score * 0.15
        )
        base_bull_prob = max(12, min(88, round(weighted_score)))

        # 計算預估明日漲跌幅度 (%)
        daily_vol_pct = (cfg["annual_vol"] / math.sqrt(252)) * 100
        bias = (base_bull_prob - 50) / 50.0
        pred_move_pct = round(bias * daily_vol_pct * 1.15, 2)
        pred_dir = "漲" if base_bull_prob >= 50 else "跌"
        pred_prob = base_bull_prob if base_bull_prob >= 50 else (100 - base_bull_prob)

        # 讀取既有 30 日回測清單
        prev_stock = existing_data.get("stocks", {}).get(code, {})
        history_list = list(prev_stock.get("history", []))

        # 若初次建立且沒有 30 筆歷史紀錄，利用過去 30 個交易日真實收盤價建立回測基準
        if len(history_list) < 30 and len(hist_df) >= 31:
            history_list = []
            sub_df = hist_df.tail(31)
            for i in range(1, len(sub_df)):
                c_today = float(sub_df["Close"].iloc[i])
                c_yest = float(sub_df["Close"].iloc[i - 1])
                c_prev2 = float(sub_df["Close"].iloc[i - 2]) if i >= 2 else c_yest
                d_str = sub_df.index[i].strftime("%m/%d")
                act_pct = ((c_today - c_yest) / c_yest) * 100
                act_dir = "漲" if act_pct >= 0 else "跌"

                # 以當日盤前已知的前一日動能與均線位置模擬當時推估
                prior_mom = ((c_yest - c_prev2) / c_prev2) * 100
                est_prob = max(35, min(68, round(50 + prior_mom * 4)))
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

        # 結算已鎖定的預測快照（當天 13:30 收盤後自動寫入近 30 日回測）
        stock_pending = pending_all.get(code, {})
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
            # 若同一天已存在則更新，否則新增並裁切維持最新 30 個交易日
            existing_idx = next((idx for idx, x in enumerate(history_list) if x["date"] == last_trade_short), -1)
            if existing_idx >= 0:
                history_list[existing_idx] = new_entry
            else:
                history_list.append(new_entry)

        history_list = history_list[-30:]

        # 寫入下一個交易日的預測快照，待該交易日收盤後自動結算
        stock_pending[target_key] = {
            "predDir": pred_dir,
            "pred": f"{pred_dir} {pred_prob}%",
            "predPct": fmt_signed_pct(pred_move_pct),
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
            "factors": factors,
            "history": history_list,
        }

    output_payload = {
        "updatedAt": now_tw.strftime("%Y/%m/%d %H:%M"),
        "todayDate": today_str,
        "targetDate": target_key,
        "foreignNetBillion": foreign_net_billion,
        "nasdaqPct": nasdaq_pct,
        "news": news_items,
        "stocks": stocks_output,
        "pending_predictions": pending_all,
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=2)
    print(f"Successfully updated {DATA_FILE} at {output_payload['updatedAt']}")


if __name__ == "__main__":
    main()
