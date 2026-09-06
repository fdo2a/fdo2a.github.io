<!-- 이 파일은 `scripts/thesis/` 안의 파일을 건드릴 때 자동으로 로드된다.
     공통 규칙은 프로젝트 루트 CLAUDE.md에 있다. -->

## 종목 thesis 감시 (2026-08-24~)
개별 종목을 계속 들고 갈 때 «내가 이 종목을 본 이유가 아직 유효한가»만 판정하는 세 번째 파이프라인. 대상은 메모리 3사(삼성전자 005930.KS·SK하이닉스 000660.KS·Micron MU), 발행은 `/thesis/` 경로. 상세는 spec `docs/superpowers/specs/2026-08-24-thesis-watch-design.md`.
- **US·KR 브리프와 성격이 반대다 — 대부분의 날에 아무것도 하지 않아야 한다.** 브리프는 매일 발행하지만 이건 변화가 없으면 파일도 안 건드리고 커밋도 알림도 없다. 「매일 돌되 보통은 아무것도 하지 마」는 프롬프트로는 안 지켜지므로(§8 매크로가 겪은 실패와 같은 구조) **상태 파일과 게이트로 기계화**했다. `scripts/thesis/gate.py`의 `check_silence()`가 **트리거 없이 페이지가 수정되면 발행을 막는다** — 이게 이 파이프라인의 존재 이유
- **수집 = GitHub Actions** `.github/workflows/collect-thesis-data.yml`(평일 08:40 UTC = 17:40 KST, KR 수집 후·루틴 전) → `scripts/collect_thesis_data.py` + `scripts/thesis/` 패키지(TDD, 85 tests)가 `thesis/data/*` 커밋. 수동: `gh workflow run collect-thesis-data.yml -f force=true`. **날짜는 KST 고정** — 러너가 UTC라 로컬과 하루 어긋난 행을 남긴 전례(2026-08-24 실측)
- **산출 3개**: `watch.json`(주가·컨센 EPS avg/low/high·P/E·P/B·BPS·다음 실적일 + 계산된 fair_value) / **`history.jsonl`(매일 1행 append — 이게 설계의 핵심.** yfinance는 오늘 컨센만 주므로 30일 변화는 우리가 쌓아야만 알 수 있고, 그 변화가 이 세 종목의 유일한 진짜 뉴스다. 20행 미만이면 되돌아보기 트리거 자동 비활성) / `thesis_state.json`(승계되는 책 — 등급·`last_seen`·`open_questions`·`changelog`)
- **등급 통제 어휘 4개**: 홀딩 강화 · 주의 · 비중 조절 검토 · kill condition. 규율은 `scripts/thesis/state.py`의 `propose()`가 강제 — 하루 한 단계·대각선 금지·**kill은 가격 축과 계약/점유율 축이 함께 깨질 때만**·악화는 즉시/회복은 3영업일 잠금(stance.json과 같은 비대칭)·트리거 없으면 이동 불가
- **1차 출처 규칙**: 공시·IR·실적자료·고객사 발표로 확인된 사건만 등급을 움직인다. 언론 단독·익명 소식통은 «추론»으로만 분류되고 단독으로는 등급을 못 바꾼다. 게이트가 `<cite>` 출처 없는 «확정 사실»을 막는다
- **페이지는 손으로 안 쓴다** — `scripts/build_thesis_pages.py`가 **산문은 `scripts/thesis/content.py`에서 저작, 숫자는 `watch.json`에서 렌더**. thesis 자체가 바뀌면 content.py를 고치고 다시 빌드(드문 일이고 changelog 필수). HTML 직접 편집 금지 — 손으로 타이핑한 수치는 반드시 흔들린다(과거 FX 방향·유가 등락률 오류 전례)
- **P/B 기준일 주의**: 분모는 마지막으로 *보고된* 재무제표다. 최근 분기 실적이 나왔어도 데이터 소스 반영 전이면 자본 증가가 안 잡혀 P/B가 높게 보인다(2026-08 하이닉스 실측: Q1 기준 7.46배). **손으로 보정하지 않는다** — 창작한 숫자보다 기준일이 명시된 낡은 숫자가 낫다. `bvps_as_of`가 페이지에 노출된다
- **밸류에이션**: 정규화이익법(FY1 컨센 EPS × 정규화율 × 정규화 P/E)과 자산법(2년 뒤 BPS × 시나리오 P/B)을 각각 계산해 평균. Bull/Base/Bear = 80/48/25% 정규화율에 30/45/25% 확률. **가정이 결과를 지배한다는 사실을 페이지에 명시** — Bull 확률을 50%로 올리면 현재가가 저평가로 바뀐다. 목표주가가 아니라 판단 보조용 기준선
- **네비게이션**: US↔KR 2방향 스위치를 3방향 pill로 교체(`index.html`·`kr/index.html`·`thesis/index.html` 셋만, 기존 포스트 50편 무수정)
- **클라우드 루틴 트리거**: `trig_01KfzghhVx3qa9eBEVjEg8Sy` — 월~금 19:00 KST(cron `0 10 * * 1-5` UTC). **KR 브리프(09:00 UTC)와 같은 레포에 push하므로 한 시간 비켜 놨다.** sonnet-5, 파이프라인은 레포 `.claude/THESIS_ORCHESTRATOR.md`
- **미완/열린 항목**: 사건 트리거가 아직 프롬프트 규칙뿐(수치 트리거만 기계화됨) · 종목 추가 시 content.py 일반화 필요 · 판정 품질이 sonnet-5로 충분한지는 실운영 후 재검토



**고칠 때**: `scripts/thesis/content.py`·`thesis_state.py`·`check_thesis.py` 를 건드리기 전에 `docs/superpowers/specs/2026-08-24-thesis-watch-design.md` 를 읽는다. 페이지는 사람이 쓰지 않는다 — 문장을 바꾸려면 `content.py` 를 바꾼다.
