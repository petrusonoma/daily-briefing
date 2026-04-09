"""
daily_briefing.py  (v2)
────────────────────────────────────────────────────────────────
하루 4회(08:00 / 13:00 / 16:00 / 21:00 KST) 실행되며
Notion 데이터베이스에 "날짜별 1페이지 + 시간대별 토글 섹션" 구조로 게시합니다.

  ┌─ 경제 브리핑 DB ────────────────────────────────┐
  │  📄 2025년 04월 09일                            │
  │    ▶ 08:00 — 장 시작 전 브리핑   (토글)         │
  │    ▶ 13:00 — 오전장 중간 점검    (토글)         │
  │    ▶ 16:00 — 장 마감 결산        (토글)         │
  │    ▶ 21:00 — 미국 장 시작 모니터링(토글)        │
  └─────────────────────────────────────────────────┘

필요 환경 변수:
  ANTHROPIC_API_KEY   Anthropic API 키
  FRED_API_KEY        FRED API 키  (fred.stlouisfed.org 무료 발급)
  NOTION_TOKEN        Notion Integration 토큰
  NOTION_DATABASE_ID  브리핑을 게시할 Notion 데이터베이스 ID
"""

import os, json, datetime, requests, xml.etree.ElementTree as ET
import yfinance as yf
from zoneinfo import ZoneInfo

ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
FRED_API_KEY       = os.environ["FRED_API_KEY"]
NOTION_TOKEN       = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]

KST       = ZoneInfo("Asia/Seoul")
NOW       = datetime.datetime.now(KST)
TODAY_STR = NOW.strftime("%Y년 %m월 %d일")
TODAY_ISO = NOW.strftime("%Y-%m-%d")
HOUR      = NOW.hour

# ── 시간대별 슬롯 ──────────────────────────────────────────────
SLOTS = {
    8 : {"label": "장 시작 전 브리핑",      "icon": "🌅",
         "focus": "전날 미국 마감 · 오늘 개장 전 점검",
         "news_q": "Korea stock market economy finance"},
    13: {"label": "오전장 중간 점검",        "icon": "☀️",
         "focus": "오전 거래량 · 업종별 흐름 확인",
         "news_q": "KOSPI Asia stock market economy"},
    16: {"label": "장 마감 결산",            "icon": "🏁",
         "focus": "국내 최종 종가 · 외국인/기관 동향",
         "news_q": "Korea stock market close economy"},
    21: {"label": "미국 장 시작 모니터링",   "icon": "🌙",
         "focus": "미국 개장 · 선물 지수 · 야간 이슈",
         "news_q": "Wall Street NYSE NASDAQ stock market"},
}

def get_slot():
    for h in sorted(SLOTS.keys(), reverse=True):
        if HOUR >= h:
            return h, SLOTS[h]
    return 8, SLOTS[8]

SLOT_HOUR, SLOT = get_slot()
SLOT_TIME = f"{SLOT_HOUR:02d}:00"


# ══════════════════════════════════════════════════════════════
# 1. 증시 & 환율
# ══════════════════════════════════════════════════════════════
TICKERS = {
    "KOSPI": "^KS11", "KOSDAQ": "^KQ11",
    "S&P500": "^GSPC", "NASDAQ": "^IXIC", "DOW": "^DJI",
    "USD/KRW": "USDKRW=X", "EUR/KRW": "EURKRW=X", "JPY/KRW": "JPYKRW=X",
}

def fetch_market_data():
    result = {}
    for name, ticker in TICKERS.items():
        try:
            data = yf.Ticker(ticker).history(period="2d")
            if len(data) >= 2:
                prev, last = data["Close"].iloc[-2], data["Close"].iloc[-1]
                chg, chg_p = last - prev, (last - prev) / prev * 100
            elif len(data) == 1:
                last, chg, chg_p = data["Close"].iloc[-1], 0, 0
            else:
                result[name] = {"error": "데이터 없음"}; continue
            result[name] = {
                "price": round(last, 2), "change": round(chg, 2),
                "change_pct": round(chg_p, 2),
                "arrow": "▲" if chg >= 0 else "▼",
                "emoji": "🟢" if chg >= 0 else "🔴",
            }
        except Exception as e:
            result[name] = {"error": str(e)}
    return result


# ══════════════════════════════════════════════════════════════
# 2. 경제 지표 (FRED)
# ══════════════════════════════════════════════════════════════
FRED_SERIES = {
    "미국 기준금리 (FFR)": "FEDFUNDS",
    "미국 CPI (전년비%)": "CPIAUCSL",
    "미국 실업률": "UNRATE",
    "미국 10년물 국채금리": "DGS10",
    "WTI 유가": "DCOILWTICO",
}

def fetch_fred(sid):
    r = requests.get("https://api.stlouisfed.org/fred/series/observations",
        params={"series_id": sid, "api_key": FRED_API_KEY, "file_type": "json",
                "sort_order": "desc", "limit": 2, "observation_start": "2020-01-01"},
        timeout=10)
    r.raise_for_status()
    obs = r.json().get("observations", [])
    if not obs: return {}
    latest, prev = obs[0], obs[1] if len(obs) > 1 else obs[0]
    try:
        val = float(latest["value"])
        chg = round(val - float(prev["value"]), 3)
    except ValueError:
        val, chg = latest["value"], None
    return {"value": val, "change": chg, "date": latest["date"]}

def fetch_economic_indicators():
    result = {}
    for label, sid in FRED_SERIES.items():
        try: result[label] = fetch_fred(sid)
        except Exception as e: result[label] = {"error": str(e)}
    return result


# ══════════════════════════════════════════════════════════════
# 3. 뉴스 (Google News RSS) — API 키 불필요, 서버 제약 없음
# ══════════════════════════════════════════════════════════════
# Google News RSS: 쿼리 기반, 완전 무료, 결과 안정적
GNEWS_BASE = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q="

SLOT_QUERIES = {
    8 : "Korea+stock+market+economy+finance",
    13: "KOSPI+Asia+stock+market+economy",
    16: "Korea+stock+market+close+economy",
    21: "Wall+Street+NYSE+NASDAQ+stock+market",
}

def _parse_gnews(url, count):
    r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    # Google News RSS는 <link> 대신 <guid>에 실제 URL이 있는 경우도 있으므로 둘 다 확인
    ns = {"media": "http://search.yahoo.com/mrss/"}
    root = ET.fromstring(r.content)
    result = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link  = (item.findtext("link") or item.findtext("guid") or "").strip()
        pub   = (item.findtext("pubDate") or "")[:16]
        source_el = item.find("source")
        source = source_el.text if source_el is not None else "Google News"
        if title and link and title != "[Removed]":
            result.append({"title": title, "url": link,
                           "source": source, "time": pub})
        if len(result) >= count:
            break
    return result

def fetch_news(query=None, count=5):
    q = SLOT_QUERIES.get(SLOT_HOUR, SLOT_QUERIES[8])
    url = GNEWS_BASE + q
    try:
        return _parse_gnews(url, count)
    except Exception as e:
        print(f"       Google News RSS 오류: {e}")
        # 폴백: 일반 비즈니스 뉴스
        try:
            return _parse_gnews(GNEWS_BASE + "stock+market+economy+finance", count)
        except Exception as e2:
            print(f"       폴백도 실패: {e2}")
            return []


# ══════════════════════════════════════════════════════════════
# 4. AI 시장 해설 (Claude API)
# ══════════════════════════════════════════════════════════════
def fetch_ai_commentary(market_data, indicators, news):
    news_titles = "\n".join(f"- {n['title']} ({n['source']})" for n in news)
    prompt = f"""오늘은 {TODAY_STR} {SLOT_TIME} KST입니다.
슬롯: {SLOT['label']} / 관점: {SLOT['focus']}

시장 데이터:
{json.dumps(market_data, ensure_ascii=False, indent=2)}

경제 지표:
{json.dumps(indicators, ensure_ascii=False, indent=2)}

뉴스 헤드라인:
{news_titles}

위 데이터를 바탕으로 한국어 시장 해설을 아래 형식으로 작성해 주세요:
---
🔍 시장 해설
[2~3문단. '{SLOT["focus"]}' 관점으로 뉴스와 지표를 연결해 분석.]

⚠️ 주목 포인트
• [리스크 또는 이벤트 2~3개]
---"""
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": ANTHROPIC_API_KEY,
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": "claude-sonnet-4-20250514", "max_tokens": 1200,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=60)
    r.raise_for_status()
    parts = [b["text"] for b in r.json().get("content", []) if b.get("type") == "text"]
    return "\n".join(parts).strip()


# ══════════════════════════════════════════════════════════════
# 5. Notion 블록 빌더
# ══════════════════════════════════════════════════════════════
def _rt(text, bold=False, color="default", url=None):
    t = {"content": text}
    if url: t["link"] = {"url": url}
    return {"type": "text", "text": t,
            "annotations": {"bold": bold, "code": False, "color": color,
                            "italic": False, "strikethrough": False, "underline": False}}

def _para(*rts):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": list(rts)}}

def _h3(text):
    return {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [_rt(text)]}}

def _bullet(rts):
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": rts}}

def _divider():
    return {"object": "block", "type": "divider", "divider": {}}

def _callout(text, emoji):
    return {"object": "block", "type": "callout",
            "callout": {"rich_text": [_rt(text)], "icon": {"type": "emoji", "emoji": emoji}}}

def _table_row(cells):
    return {"type": "table_row",
            "table_row": {"cells": [[{"type": "text", "text": {"content": c}}] for c in cells]}}

def market_table_block(market_data):
    rows = [_table_row(["지수/환율", "현재가", "변동", "등락률"])]
    for name, d in market_data.items():
        if "error" in d:
            rows.append(_table_row([name, "오류", "-", "-"]))
        else:
            rows.append(_table_row([
                f"{d['emoji']} {name}",
                f"{d['price']:,.2f}",
                f"{d['arrow']} {abs(d['change']):,.2f}",
                f"{d['arrow']} {abs(d['change_pct']):.2f}%",
            ]))
    return {"object": "block", "type": "table",
            "table": {"table_width": 4, "has_column_header": True,
                      "has_row_header": False, "children": rows}}

def indicator_bullets(indicators):
    blocks = []
    for label, d in indicators.items():
        if "error" in d:
            text = f"{label}: 오류"
        else:
            v  = d.get("value", "N/A")
            ch = d.get("change")
            dt = d.get("date", "")
            ch_str = f"  {'▲' if ch >= 0 else '▼'} {abs(ch):.3f}" if ch is not None else ""
            text = f"{label}: {v}{ch_str}  ({dt})"
        blocks.append(_bullet([_rt(text)]))
    return blocks

def news_bullets(news):
    """뉴스 제목에 원문 링크를 달아 bullet으로 반환."""
    blocks = []
    for n in news:
        blocks.append(_bullet([
            _rt(n["title"], url=n["url"]),
            _rt(f"  {n['source']}", color="gray"),
        ]))
    return blocks

def commentary_blocks(text):
    blocks = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or line == "---": continue
        if line.startswith(("•", "-")):
            blocks.append(_bullet([_rt(line.lstrip("•- "))]))
        elif any(line.startswith(p) for p in ("🔍", "⚠️")):
            blocks.append(_h3(line))
        else:
            blocks.append(_para(_rt(line)))
    return blocks

def build_toggle(market_data, indicators, news, commentary):
    title = f"{SLOT['icon']} {SLOT_TIME} — {SLOT['label']}"
    children = [
        _callout(f"{NOW.strftime('%H:%M')} KST · {SLOT['focus']}", SLOT["icon"]),
        _divider(),
        _h3("📈 증시 & 환율"),
        market_table_block(market_data),
        _divider(),
        _h3("📊 경제 지표"),
        *indicator_bullets(indicators),
        _divider(),
        _h3("📰 주요 뉴스 (제목 클릭 → 원문)"),
        *news_bullets(news),
        _divider(),
        *commentary_blocks(commentary),
    ]
    return {"object": "block", "type": "toggle",
            "toggle": {"rich_text": [_rt(title, bold=True)], "children": children}}


# ══════════════════════════════════════════════════════════════
# 6. Notion 업서트 (오늘 페이지 찾기 → 없으면 생성 → 토글 추가)
# ══════════════════════════════════════════════════════════════
HDR = {"Authorization": f"Bearer {NOTION_TOKEN}",
       "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

def find_today_page():
    r = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query",
        headers=HDR,
        json={"filter": {"property": "Date", "date": {"equals": TODAY_ISO}}},
        timeout=15)
    r.raise_for_status()
    results = r.json().get("results", [])
    return results[0]["id"] if results else None

def create_today_page():
    r = requests.post("https://api.notion.com/v1/pages", headers=HDR, json={
        "parent": {"database_id": NOTION_DATABASE_ID},
        "icon": {"type": "emoji", "emoji": "📊"},
        "properties": {
            "Name": {"title": [{"text": {"content": f"📊 경제 브리핑 — {TODAY_STR}"}}]},
            "Date": {"date": {"start": TODAY_ISO}},
        },
        "children": [],
    }, timeout=20)
    r.raise_for_status()
    return r.json()["id"]

def append_toggle(page_id, toggle_block):
    r = requests.patch(
        f"https://api.notion.com/v1/blocks/{page_id}/children",
        headers=HDR, json={"children": [toggle_block]}, timeout=30)
    r.raise_for_status()


# ══════════════════════════════════════════════════════════════
# 7. 메인
# ══════════════════════════════════════════════════════════════
def main():
    print(f"[{TODAY_STR} {SLOT_TIME}] {SLOT['label']} 브리핑 시작...")

    print("  1/5 증시·환율 수집 중...")
    market_data = fetch_market_data()

    print("  2/5 경제 지표 수집 중 (FRED)...")
    indicators = fetch_economic_indicators()

    print(f"  3/5 뉴스 수집 중 (NewsAPI)...")
    news = fetch_news(SLOT["news_q"])

    print("  4/5 AI 시장 해설 생성 중...")
    commentary = fetch_ai_commentary(market_data, indicators, news)

    print("  5/5 Notion 업서트 중...")
    page_id = find_today_page()
    if page_id:
        print(f"       기존 페이지 발견 → 토글 추가")
    else:
        print(f"       오늘 페이지 없음 → 새 페이지 생성")
        page_id = create_today_page()
    append_toggle(page_id, build_toggle(market_data, indicators, news, commentary))

    url = f"https://notion.so/{page_id.replace('-', '')}"
    print(f"  ✅ 완료: {url}")

if __name__ == "__main__":
    main()
