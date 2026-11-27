"""이력 종가 비교 — 알림만(2026-11-27 「숫자는 코드가 채운다」 1차 §7).

수집 때, 어제 이력 행(`data/history/market.jsonl`)에 저장한 종가와 오늘 받은 일봉 가운데 **같은 관측일의 봉**의 종가를
견준다. 다르면 (자산·관측일·저장 값·다시 받은 값)과, 최근 14일 검증 기록(`verification/us/*.json`)의 `fills` 에서 그 값을
쓴 글·칸을 찾아 알린다. **발행을 막지 않고 행을 invalid 로 찍지도 않는다.**

- 대상: 미국 지수·업종 ETF·주가 묶음(일봉). 환율·원자재는 16:00 ET 컷이라 일봉과 견주지 않는다.
- 짝짓기: 이력 행의 `dates`(자산별 관측일, 이 판부터 기록)가 있는 행만. 같은 날짜의 봉이 없으면 견주지 않는다.
- 헛알림: 일봉은 배당·분할 조정값(auto_adjust)이라, 관측일 **이후**(그날 포함) 봉에 배당·분할이 있으면 견주지 않는다
  (그 뒤 배당이 그날 종가를 다시 조정한다).
- 다르다 = 소수 둘째 자리에서 보이는 차이(|차| ≥ 0.005).
"""
import glob
import json
import os
from datetime import date as _date, timedelta

GROUPS = ('indices', 'sectors', 'memory', 'ai_infra', 'mlcc')
TOL = 0.005
WINDOW_DAYS = 14
GATE = 'check_number_sources'


def previous_row(rows, today):
    """오늘보다 앞선 마지막 이력 행(관측일 기록이 있는 것만) | None."""
    cand = [r for r in rows if isinstance(r, dict) and (r.get('report_date') or '') < today]
    if not cand:
        return None
    row = max(cand, key=lambda r: r['report_date'])
    return row if isinstance(row.get('dates'), dict) else None


def compare(row, bars, tickers):
    """→ (mismatches, 견준 수, 건너뛴 이유별 수). bars = {티커: (날짜들, 종가들, 배당·분할 날짜 집합)},
    tickers = {묶음: {이름: 티커}}."""
    out, checked, skipped = [], 0, {}

    def skip(why):
        skipped[why] = skipped.get(why, 0) + 1
    for group in GROUPS:
        for name, stored in (row.get(group) or {}).items():
            d = ((row.get('dates') or {}).get(group) or {}).get(name)
            t = (tickers.get(group) or {}).get(name)
            if not d or not t:
                skip('관측일 없음')
                continue
            got = bars.get(t)
            if not got:
                skip('일봉 없음')
                continue
            dates, closes, actions = got
            if d not in dates:
                skip('같은 날짜 봉 없음')
                continue
            if any(a >= d for a in actions):
                skip('배당·분할')
                continue
            checked += 1
            fresh = closes[dates.index(d)]
            if abs(float(stored) - float(fresh)) >= TOL:
                out.append({'group': group, 'asset': name, 'date': d, 'stored': float(stored), 'fresh': float(fresh)})
    return out, checked, skipped


def find_posts(repo, mismatches, today, days=WINDOW_DAYS):
    """불일치마다 그 값을 쓴 글·칸(최근 `days` 일 기록의 `fills`). 기록이 없는 발행 글·fills 없는 기록은 「조회 불가」."""
    start = (_date.fromisoformat(today) - timedelta(days=days)).isoformat()
    records, unreadable = {}, []
    for p in sorted(glob.glob(os.path.join(repo, 'posts', '*.html'))):
        d = os.path.basename(p)[:-5]
        if not (start <= d <= today) or len(d) != 10:
            continue
        rp = os.path.join(repo, 'verification', 'us', f'{d}.json')
        try:
            with open(rp, encoding='utf-8') as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            unreadable.append({'post': f'posts/{d}.html', 'why': '레포에 검증 기록이 없다'})
            continue
        g = next((x for x in rec.get('gates') or [] if isinstance(x, dict) and x.get('name') == GATE), None)
        fills = ((g or {}).get('sources') or {}).get('fills')
        if not isinstance(fills, list):
            unreadable.append({'post': f'posts/{d}.html', 'why': '기록에 fills 없음'})
            continue
        records[d] = fills
    for m in mismatches:
        m['posts'] = [{'post': f'posts/{d}.html', 'ref': f.get('ref'), 'text': f.get('text')}
                      for d, fills in sorted(records.items()) for f in fills
                      if isinstance(f, dict) and f.get('group') == m['group'] and f.get('asset') == m['asset']
                      and f.get('date') == m['date']]
    return unreadable


def report(today, mismatches, checked, skipped, unreadable):
    """이력에 덧붙일 한 행 + Actions 경고 줄들."""
    row = {'report_date': today, 'checked': checked, 'skipped': skipped, 'mismatches': mismatches,
           'unreadable': unreadable}
    lines = []
    for m in mismatches:
        used = ', '.join(f"{p['post']} 「{p['text']}」" for p in m.get('posts') or []) or \
            f'그 값을 쓴 글 없음(최근 {WINDOW_DAYS}일 기록 기준)'
        lines.append(f"::warning::이력 종가 불일치 {m['asset']} {m['date']}: 저장 {m['stored']:.4f} · 다시 받은 값 "
                     f"{m['fresh']:.4f} — {used}")
    if mismatches and unreadable:
        lines.append('::warning::이력 종가 불일치 — 조회 불가 글: '
                     + ', '.join(f"{u['post']}({u['why']})" for u in unreadable))
    return row, lines
