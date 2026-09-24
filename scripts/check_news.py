#!/usr/bin/env python3
"""Publication gate for 「오늘의 뉴스」.

Run from the repo clone, against the writer's output in the routine workspace:

  python scripts/check_news.py --html morning_brief_2026-09-19.html --datadir .
  python scripts/check_news.py --html kr_brief_2026-09-25.html --datadir kr/data --market kr --date 2026-09-25

Exit 0 = publishable. Exit 1 = violations printed, one per line; hand them back to
the writer subagent verbatim and re-run.

수집분이 없는 날은 조용히 통과한다 — 피드가 죽었다고 브리프를 세우지 않는다.
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kr.news import DIGEST_CATEGORIES as KR_CATEGORIES  # noqa: E402
from us.news import DIGEST_CATEGORIES as US_CATEGORIES  # noqa: E402
from us.news_gate import check  # noqa: E402

# KR 은 네이버증권 주요뉴스(`kr/data/news/<date>.json`, `fetch_kr_news.py`). 갈래만 다르고
# 대조 규칙은 같다(2026-09-24).
CATEGORIES = {'us': US_CATEGORIES, 'kr': KR_CATEGORIES}


def load_collected(datadir, report_date=None):
    """그날 수집분. 날짜를 안 주면 news/ 에서 가장 최근 것을 쓴다."""
    newsdir = os.path.join(datadir, 'news')
    if report_date:
        path = os.path.join(newsdir, f'{report_date}.json')
    else:
        found = sorted(glob.glob(os.path.join(newsdir, '*.json')))
        if not found:
            return None, None
        path = found[-1]
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh), path
    except FileNotFoundError:
        return None, path
    except Exception as e:
        print(f'WARN: could not read {path}: {e}', file=sys.stderr)
        return None, path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='.', help='news/<date>.json 을 담은 워크스페이스')
    ap.add_argument('--date', default=None,
                    help='발행일. 주면 그날 수집분만 쓰고 날짜 불일치를 위반으로 본다 '
                         '— 없으면 최신 파일을 집어 어제 수집분이 오늘의 근거가 된다')
    ap.add_argument('--market', choices=sorted(CATEGORIES), default='us',
                    help='섹션 의무를 거는 갈래. KR 은 --datadir kr/data 와 함께')
    args = ap.parse_args()

    with open(args.html, encoding='utf-8') as fh:
        html = fh.read()

    collected, path = load_collected(args.datadir, args.date)
    if not collected or not (collected.get('items') or []):
        # **검사를 건너뛰지 않는다**(2026-09-19 codex 검토 #1). 수집이 실패한 날이
        # 지어낸 뉴스가 실릴 확률이 가장 높은 날이다. 면제되는 것은 섹션을 실을
        # 의무이지, 실은 것을 대조받을 의무가 아니다.
        print(f'뉴스 수집분 없음({path or "news/"}) — 섹션 의무는 면제, '
              f'표식 대조는 그대로 한다')
        collected = collected or {'items': []}

    violations = check(html, collected, report_date=args.date,
                       categories=CATEGORIES[args.market])
    if violations:
        print(f'뉴스 게이트 위반 {len(violations)}건 ({path}):', file=sys.stderr)
        for v in violations:
            print(f'  - {v}', file=sys.stderr)
        return 1
    n = len(collected.get('items') or [])
    print(f'뉴스 게이트 통과 — 수집 {n}건 대조 완료')
    return 0


if __name__ == '__main__':
    sys.exit(main())
