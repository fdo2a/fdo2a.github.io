"""CLI 경로로 배치 날짜 컷을 시험한다 — 순수 함수만 보면 날짜를 빠뜨린 호출자가 옛 배치로 새는 것을
못 본다(codex 설계 검토 2026-10-19 #1·#11)."""
import json
import subprocess
import sys
from pathlib import Path

from .test_stance_gate import EVAL, PARAS, STANCE
from .test_stance_gate_layout import V2, _doc

SCRIPT = Path(__file__).resolve().parents[2] / "check_kr_stance.py"
SIX = (f'<section><h2>전략 코멘트</h2>'
       + "".join(f'<p data-lede="{k}">{PARAS[k]}</p>' for k in V2 + ["review"])
       + '</section><section><h2>오늘의 장</h2><p>딴 얘기</p></section>')


def _run(tmp_path, html, report_date, ledger_date=None):
    d = tmp_path / "data"
    d.mkdir(exist_ok=True)
    (d / "kr_stance_eval.json").write_text(json.dumps(EVAL, ensure_ascii=False))
    if report_date is not None:
        (d / "kr_market_data.json").write_text(json.dumps({"report_date": report_date}))
    nxt = {**STANCE, "date": ledger_date if ledger_date is not None else report_date,
           "alternative": "외국인 매도가 바닥을 지나 매도 소진이 시작됐다는 설명이다.",
           "distinguisher": "10월 21일까지 세 세션의 외국인 코스피 수급 합계로 가른다.",
           "wait_for": "10월 21일 마감까지의 외국인 코스피 수급과 코스피 종가를 기다린다."}
    (tmp_path / "next.json").write_text(json.dumps(nxt, ensure_ascii=False))
    (tmp_path / "post.html").write_text(html)
    r = subprocess.run([sys.executable, str(SCRIPT), "--html", str(tmp_path / "post.html"),
                        "--datadir", str(d), "--next", str(tmp_path / "next.json")],
                       capture_output=True, text=True)
    return r.returncode, r.stdout


def test_old_layout_passes_on_10_19(tmp_path):
    assert _run(tmp_path, SIX, "2026-10-19")[0] == 0


def test_new_layout_passes_on_10_19(tmp_path):
    assert _run(tmp_path, _doc(), "2026-10-19")[0] == 0


def test_old_layout_rejected_from_10_20(tmp_path):
    code, out = _run(tmp_path, SIX, "2026-10-20")
    assert code == 1 and "review" in out


def test_new_layout_passes_on_10_20(tmp_path):
    assert _run(tmp_path, _doc(), "2026-10-20")[0] == 0


def test_missing_report_date_fails(tmp_path):
    code, out = _run(tmp_path, _doc(), None, ledger_date="")
    assert code == 1 and "report_date" in out


def test_ledger_date_must_match_report_date(tmp_path):
    code, out = _run(tmp_path, _doc(), "2026-10-20", ledger_date="2026-10-19")
    assert code == 1 and "2026-10-19" in out


import pytest  # noqa: E402


@pytest.mark.parametrize("bad", ["2026-10-19junk", "2026-10-020", "2026-13-01", "20261019"])
def test_malformed_report_date_fails(tmp_path, bad):
    # codex 구현 검토 2026-10-20 #6 — 문자열 비교로는 형식이 틀린 날짜가 옛 배치를 고른다
    code, out = _run(tmp_path, SIX, bad)
    assert code == 1 and "날짜" in out
