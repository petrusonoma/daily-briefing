# 📊 매일 아침 경제 브리핑 → Notion 자동화

매일 오전 8시(KST)에 GitHub Actions가 자동으로 실행되어
주요 증시, 환율, 경제 지표, AI 뉴스 요약을 Notion 페이지에 게시합니다.

---

## 🗂️ 파일 구조

```
├── daily_briefing.py                  # 메인 스크립트
└── .github/
    └── workflows/
        └── daily_briefing.yml         # GitHub Actions 자동화
```

---

## 🔑 1단계 — API 키 발급 (3개, 모두 무료)

### ① Anthropic API 키
1. https://console.anthropic.com 접속 → 회원가입/로그인
2. **API Keys** 메뉴 → **Create Key**
3. 복사해 두기

### ② FRED API 키 (미국 경제 지표)
1. https://fred.stlouisfed.org/docs/api/api_key.html 접속
2. 이메일로 무료 가입 → API 키 즉시 발급
3. 복사해 두기

### ③ Notion Integration 토큰
1. https://www.notion.so/my-integrations 접속
2. **+ New integration** 클릭
3. 이름 입력 (예: `Daily Briefing`) → **Submit**
4. **Internal Integration Token** 복사
5. ⚠️ Notion에서 브리핑을 게시할 **데이터베이스 페이지**를 열고
   우측 상단 `···` → **Add connections** → 방금 만든 integration 선택 (연결 필수!)

---

## 🗄️ 2단계 — Notion 데이터베이스 준비

Notion에서 새 **데이터베이스** 페이지를 만들고 아래 속성을 추가합니다:

| 속성 이름 | 타입   |
|-----------|--------|
| Name      | Title  |
| Date      | Date   |

데이터베이스 URL에서 **Database ID** 추출:
```
https://www.notion.so/yourworkspace/【여기가-Database-ID】?v=...
```
(하이픈 포함 32자리 문자열)

---

## ⚙️ 3단계 — GitHub 저장소 설정

1. 이 파일들을 **새 GitHub 저장소**에 push
2. 저장소 → **Settings** → **Secrets and variables** → **Actions**
3. 아래 4개 Secret 추가:

| Secret 이름        | 값                         |
|--------------------|----------------------------|
| `ANTHROPIC_API_KEY`  | Anthropic API 키          |
| `FRED_API_KEY`       | FRED API 키               |
| `NOTION_TOKEN`       | Notion Integration 토큰   |
| `NOTION_DATABASE_ID` | Notion 데이터베이스 ID     |

---

## ▶️ 4단계 — 첫 실행 테스트

저장소의 **Actions** 탭 → **Daily Economic Briefing** → **Run workflow** 클릭

성공 시 Notion 데이터베이스에 오늘 날짜의 브리핑 페이지가 생성됩니다! 🎉

---

## 📅 실행 스케줄 변경

`daily_briefing.yml`의 cron 표현식을 수정합니다:

```yaml
# 매일 오전 7시 KST = UTC 22:00 (전날)
- cron: "0 22 * * *"

# 평일(월~금)만 실행
- cron: "0 23 * * 1-5"
```

---

## 💡 참고사항

- **KOSPI/KOSDAQ** 데이터는 장 마감 후 업데이트됩니다 (15:30 KST 이후 실행 권장).
- 미국 증시 데이터는 **전일 종가** 기준입니다 (뉴욕 시장은 KST 기준 새벽 마감).
- FRED 지표는 월별 발표 주기가 있어 **최신 발표 데이터**가 표시됩니다.
- Claude API 비용: 1회 실행 시 약 **$0.003~0.01** 수준 (매우 저렴).
