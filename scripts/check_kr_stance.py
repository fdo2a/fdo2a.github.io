#!/usr/bin/env python3
"""§2 전략 코멘트 · 판단 원장 게이트.

python3 scripts/check_kr_stance.py --html kr_brief_2026-09-22.html --datadir kr/data \
    --next kr_stance_next.json

Exit 0 = 발행 가능. Exit 1 = 위반이 한 줄씩 찍힌다 — 그대로 writer 에게 돌려주고
다시 돌린다. 비-코어가 아니다: 원장이 틀어지면 다음 회차의 복기가 통째로 거짓이 된다.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kr import stance as kr_stance          # noqa: E402
from kr.stance_gate import check, liquidity_index, parse_day   # noqa: E402


def _load(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True)
    ap.add_argument("--datadir", default="kr/data")
    ap.add_argument("--next", dest="next_path", default="kr_stance_next.json",
                    help="작성자가 낸 다음 회차 원장")
    args = ap.parse_args()

    with open(args.html, encoding="utf-8") as f:
        html_doc = f.read()
    nxt = _load(args.next_path)
    ev = _load(os.path.join(args.datadir, "kr_stance_eval.json"))

    violations = []
    if nxt is None:
        violations.append(f"{args.next_path} 가 없다 — 오늘 판단을 원장에 남겨야 내일이 복기한다")
    else:
        violations += [f"원장: {x}" for x in kr_stance.validate(nxt)]
    liquidity = liquidity_index(_load(os.path.join(args.datadir, "kr_top_value.json")),
                                _load(os.path.join(args.datadir, "kr_index_etf.json")))
    # 배치 계약(stance_gate.LAYOUT_V2_FROM)은 발행일로 고른다 — 수집 파일의 report_date 가 정본,
    # 없으면 작성자가 낸 원장의 date.
    md = _load(os.path.join(args.datadir, "kr_market_data.json")) or {}
    report_date = md.get("report_date") or (nxt or {}).get("date")
    if not report_date:
        violations.append("report_date 를 알 수 없다(kr_market_data.json·원장 date 둘 다 없다) — "
                          "배치 계약을 고를 수 없어 발행하지 않는다")
    elif parse_day(report_date) is None:
        violations.append(f"report_date 「{report_date}」가 YYYY-MM-DD 날짜가 아니다 — 배치 계약을 고를 수 없다")
    elif nxt and md.get("report_date") and nxt.get("date") != md["report_date"]:
        violations.append(f"원장 date 가 {nxt.get('date')} 인데 수집 데이터는 {md['report_date']} 다 — "
                          "오늘 판단을 오늘 날짜로 적는다")
    violations += check(html_doc, nxt or {}, ev or {}, liquidity, report_date=report_date)

    if violations:
        print(f"고칠 것 {len(violations)}건 — {args.html}")
        for x in violations:
            print(f"- {x}")
        return 1
    print(f"§2·판단 원장 이상 없음 — {args.html}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
