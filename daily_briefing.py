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
            # period="5d"로 넓게 가져온 뒤 NaN 행 제거 → 유효한 마지막 2개 사용
            data = yf.Ticker(ticker).history(period="5d")
            data = data.dropna(subset=["Close"])
            if len(data) >= 2:
                prev, last = data["Close"].iloc[-2], data["Close"].iloc[-1]
                chg  = last - prev
                chg_p = (chg / prev * 100) if prev else 0
                note = ""
            elif len(data) == 1:
                last, chg, chg_p = data["Close"].iloc[-1], 0, 0
                note = "전일종가"  # 장 미개장 시 전일 종가 표시
            else:
                result[name] = {"error": "데이터 없음"}; continue
            result[name] = {
                "price"     : round(float(last), 2),
                "change"    : round(float(chg), 2),
                "change_pct": round(float(chg_p), 2),
                "arrow"     : "▲" if chg >= 0 else "▼",
                "emoji"     : "🟢" if chg >= 0 else "🔴",
                "note"      : note,
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
# 3. 뉴스 수집
#    - 조선비즈: RSS 25건 → Claude가 투자 관점으로 8개 선별
#    - 매일경제: 랭킹 페이지 스크래핑 → 순위 그대로 Top10
# ══════════════════════════════════════════════════════════════
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# 조선비즈 RSS — 여러 URL 순서대로 시도
CHOSUNBIZ_RSS_URLS = [
    "https://biz.chosun.com/arc/outboundfeeds/rss/",
    "https://biz.chosun.com/arc/outboundfeeds/rss/?outputType=xml",
    "https://www.chosun.com/arc/outboundfeeds/rss/category/economy/",
    "https://news.google.com/rss/search?q=조선비즈+경제+증시&hl=ko&gl=KR&ceid=KR:ko",
]
def _parse_rss_url(url, source_name, pool):
    """단일 RSS URL을 파싱해 기사 목록 반환."""
    r = requests.get(url, timeout=12, headers=_HEADERS)
    r.raise_for_status()
    # 인코딩 문제 대비
    content_bytes = r.content
    # XML 선언의 인코딩과 실제 인코딩이 다를 경우 대비
    try:
        root = ET.fromstring(content_bytes)
    except ET.ParseError:
        root = ET.fromstring(content_bytes.decode("utf-8", errors="replace").encode("utf-8"))
    result = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        # CDATA 안의 텍스트도 처리
        if not title:
            title_el = item.find("title")
            title = (title_el.text or "") if title_el is not None else ""
        title = title.strip()
        link  = (item.findtext("link") or "").strip()
        if not link:
            guid = item.find("guid")
            link = (guid.text or "") if guid is not None else ""
        link = link.strip()
        pub   = (item.findtext("pubDate") or "")[:16]
        if title and link and "http" in link:
            result.append({"title": title, "url": link, "source": source_name, "time": pub})
        if len(result) >= pool:
            break
    return result

# ── 조선비즈 RSS 풀 수집 ─────────────────────────────────────
def _fetch_chosunbiz_pool(pool=25):
    for url in CHOSUNBIZ_RSS_URLS:
        try:
            result = _parse_rss_url(url, "조선비즈", pool)
            if result:
                print(f"       조선비즈 RSS ({url.split('/')[2]}): {len(result)}건 수집")
                return result
            print(f"       조선비즈 RSS 0건 ({url[:50]}...)")
        except Exception as e:
            print(f"       조선비즈 RSS 실패 ({url[:50]}): {e}")
    print("       조선비즈 RSS 전체 실패")
    return []

# ── Claude 투자 관점 선별 ────────────────────────────────────
def _claude_select(candidates, count=8):
    """
    투자자 관점 4가지 기준으로 Claude가 최종 뉴스를 선별:
    1. 시장 직접 영향도 (주가/환율/금리 즉각 영향)
    2. 매크로 경제 지표 (CPI/고용/GDP 발표)
    3. 주요 기업/산업 이슈 (시총 상위 종목, 주도 섹터)
    4. 지정학/정책 리스크 (무역/관세/규제)
    제외: 단순 시황 요약, 연예/스포츠, 광고성 보도자료
    """
    candidate_list = "\n".join(
        f"{i+1}. {n['title']}" for i, n in enumerate(candidates)
    )
    prompt = f"""당신은 주식 투자자를 위한 뉴스 큐레이터입니다.
아래 기사 목록에서 투자자에게 가장 중요한 {count}개를 선별하세요.

[선별 기준 — 우선순위 순]
1. 시장 직접 영향도: 주가·환율·금리에 즉각적인 영향 (금리 결정, 환율 급변, 외국인 대규모 매매)
2. 매크로 경제 지표: CPI·고용·GDP·무역수지 등 지표 발표
3. 주요 기업/산업 이슈: 삼성전자·SK하이닉스 등 시총 상위 종목 실적·계약, 반도체·2차전지·바이오 업황
4. 지정학·정책 리스크: 미중 무역갈등·관세·정부 규제 등 시장 불확실성

[제외]
- 단순 시황 요약 ("코스피 소폭 상승" 등)
- 연예·스포츠·사회면 기사
- 광고성 보도자료
- 특정 종목 급등/급락 단순 보도 ("OO주 XX% 급등" 등)

[기사 목록]
{candidate_list}

아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{"selected": [{{"index": 1, "reason": "선택이유15자이내"}}, ...]}}"""

    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": ANTHROPIC_API_KEY,
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": "claude-sonnet-4-20250514", "max_tokens": 400,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=30)
    r.raise_for_status()
    raw = "".join(b["text"] for b in r.json().get("content", []) if b.get("type") == "text")
    try:
        data = json.loads(raw.strip())
        selected = []
        for item in data.get("selected", []):
            idx = item["index"] - 1
            if 0 <= idx < len(candidates):
                news = dict(candidates[idx])
                news["reason"] = item.get("reason", "")
                selected.append(news)
        print(f"       Claude 선별 완료: {len(selected)}건")
        return selected[:count]
    except Exception as e:
        print(f"       Claude 선별 파싱 오류 ({e}) → 상위 {count}건 반환")
        return candidates[:count]

def fetch_chosunbiz_top8():
    """조선비즈 RSS 수집 → Claude 선별 → 8건 반환."""
    try:
        pool = _fetch_chosunbiz_pool(25)
        return _claude_select(pool, 8) if pool else []
    except Exception as e:
        print(f"       조선비즈 오류: {e}")
        return []

# ── 매일경제 Top10 스크래핑 ─────────────────────────────────
MK_MOBILE_URL = "https://m.mk.co.kr/news/ranking/"
MK_RSS_URL    = "https://www.mk.co.kr/rss/30000001/"
MK_EXCLUDE    = ["기사 속 종목이야기", "종목이야기", "주간 핫클릭"]

def fetch_mk_top10():
    """
    매일경제 Top10 수집
    1차: m.mk.co.kr/news/ranking/ (모바일, 서버사이드 렌더링)
    폴백: mk.co.kr/rss/30000001/ (RSS 최신 10건)
    """
    from bs4 import BeautifulSoup

    # ── 1차: 모바일 랭킹 페이지 ──────────────────────────────
    try:
        mobile_headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Mobile/15E148 Safari/604.1"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": "https://m.mk.co.kr/",
        }
        r = requests.get(MK_MOBILE_URL, headers=mobile_headers, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")

        result = []
        seen   = set()

        # 모바일 페이지 링크 전체에서 뉴스 URL 패턴 추출
        for a in soup.find_all("a", href=True):
            href  = a["href"]
            title = a.get_text(strip=True)

            # URL 정규화
            if href.startswith("/"):
                href = "https://m.mk.co.kr" + href
            if not href.startswith("http"):
                continue

            # 뉴스 URL 필터 (숫자 article ID 포함)
            if "/news/" not in href:
                continue
            # 제외 키워드 필터
            if any(kw in title for kw in MK_EXCLUDE):
                continue
            # 너무 짧거나 중복 제거
            if len(title) < 10 or href in seen:
                continue

            seen.add(href)
            result.append({
                "rank"  : len(result) + 1,
                "title" : title,
                "url"   : href,
                "source": "매일경제",
                "time"  : "",
            })
            if len(result) >= 10:
                break

        if len(result) >= 5:
            print(f"       매일경제 모바일: {len(result)}건 수집")
            return result

        print(f"       매일경제 모바일 결과 부족({len(result)}건) → RSS 폴백")

    except Exception as e:
        print(f"       매일경제 모바일 실패: {e} → RSS 폴백")

    # ── 폴백: RSS ─────────────────────────────────────────────
    try:
        r = requests.get(MK_RSS_URL, headers=_HEADERS, timeout=12)
        r.raise_for_status()
        root   = ET.fromstring(r.content)
        result = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link") or "").strip()
            if not title or not link:
                continue
            if any(kw in title for kw in MK_EXCLUDE):
                continue
            result.append({
                "rank"  : len(result) + 1,
                "title" : title,
                "url"   : link,
                "source": "매일경제",
                "time"  : (item.findtext("pubDate") or "")[:16],
            })
            if len(result) >= 10:
                break
        print(f"       매일경제 RSS 폴백: {len(result)}건 수집")
        return result

    except Exception as e:
        print(f"       매일경제 RSS 폴백도 실패: {e}")
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
    rows = [_table_row(["지수/환율", "현재가", "변동", "등락률", "비고"])]
    for name, d in market_data.items():
        if "error" in d:
            rows.append(_table_row([name, "오류", "-", "-", ""]))
        else:
            rows.append(_table_row([
                f"{d['emoji']} {name}",
                f"{d['price']:,.2f}",
                f"{d['arrow']} {abs(d['change']):,.2f}",
                f"{d['arrow']} {abs(d['change_pct']):.2f}%",
                d.get("note", ""),
            ]))
    return {"object": "block", "type": "table",
            "table": {"table_width": 5, "has_column_header": True,
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

def chosunbiz_news_bullets(news):
    """조선비즈 선별 뉴스 — 제목 링크 + 선별 이유."""
    blocks = []
    for n in news:
        rts = [_rt(n["title"], url=n["url"])]
        if n.get("reason"):
            rts.append(_rt(f"  · {n['reason']}", color="gray"))
        blocks.append(_bullet(rts))
    return blocks

def mk_top10_bullets(news):
    """매일경제 Top10 — 순위 번호 + 제목 링크."""
    blocks = []
    for n in news:
        rank_text = f"{n.get('rank', '')}위  "
        rts = [_rt(rank_text, bold=True), _rt(n["title"], url=n["url"])]
        blocks.append(_bullet(rts))
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

def build_toggle(market_data, indicators, chosun_news, mk_news, commentary):
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
        _h3("📰 조선비즈 — AI 선별 주요 뉴스 (투자 관점)"),
        *chosunbiz_news_bullets(chosun_news),
        _divider(),
        _h3("🏆 매일경제 — 실시간 Top 10"),
        *mk_top10_bullets(mk_news),
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

    print("  1/6 증시·환율 수집 중...")
    market_data = fetch_market_data()

    print("  2/6 경제 지표 수집 중 (FRED)...")
    indicators = fetch_economic_indicators()

    print("  3/6 조선비즈 RSS 수집 + Claude 선별 중...")
    chosun_news = fetch_chosunbiz_top8()

    print("  4/6 매일경제 Top10 스크래핑 중...")
    mk_news = fetch_mk_top10()

    all_news = chosun_news + mk_news
    print("  5/6 AI 시장 해설 생성 중...")
    commentary = fetch_ai_commentary(market_data, indicators, all_news)

    print("  6/6 Notion 업서트 중...")
    page_id = find_today_page()
    if page_id:
        print(f"       기존 페이지 발견 → 토글 추가")
    else:
        print(f"       오늘 페이지 없음 → 새 페이지 생성")
        page_id = create_today_page()
    append_toggle(page_id, build_toggle(market_data, indicators, chosun_news, mk_news, commentary))

    url = f"https://notion.so/{page_id.replace('-', '')}"
    print(f"  ✅ 완료: {url}")

if __name__ == "__main__":
    main()
