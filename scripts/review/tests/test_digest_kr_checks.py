"""KR 수집 검사 기록의 알림 — 차단은 당일 미발행 감시 줄에, 경고까지 전부는 다음 날 아침 요약에(2026-11-12).

알림과 관찰 보고는 실행 manifest 의 `checks` 만 읽는다 — 같은 날 뒤의 정상 재수집이 고정 경로를 덮어도
앞 실행의 기록이 남는다. 줄은 고정 문구만 싣는다(원문·긴 값 없음).
spec: docs/superpowers/specs/2026-11-12-kr-missing-vs-zero.md
"""
import json
from datetime import datetime, timedelta, timezone

from kr import index_check as IC
from review import digest as D
from review import publish_watch as W
from review.tests import prepub_fixture as F

KST = timezone(timedelta(hours=9))
DAY = "2026-11-12"


def ip(kospi=None, kosdaq=None, mode="warn", cfg="ok"):
    return {"mode": mode, "config_status": cfg,
            "KOSPI": kospi or {"status": "ok", "naver_pct": -0.61, "derived_pct": -0.607, "cross_note": False},
            "KOSDAQ": kosdaq or {"status": "ok", "naver_pct": 0.5, "derived_pct": 0.4996, "cross_note": False}}


def checks(index_pct=None, flows=None, top=None):
    return {"index_pct": index_pct or ip(),
            "flows": flows or {"KOSPI": {"state": "ok", "faults": []}, "KOSDAQ": {"state": "ok", "faults": []}},
            "top_value": top or {"rows": 950, "dash": 70, "bad": 0, "dash_top100": 0, "positive_rows": 10}}


def manifest(ck, date=DAY, rid="r1"):
    m = {"market": "kr", "trade_date": date, "run_id": rid}
    if ck is not None:
        m["checks"] = ck
    return m


def repo_with(tmp_path, runs=(), fallbacks=(), market_data=None, raw=None):
    repo = F.init(tmp_path)
    for date, rid, man in runs:
        F.write(repo, f"versions/kr/{date}/runs/{rid}/manifest.json", json.dumps(man))
    for date, rid in fallbacks:
        F.write(repo, f"versions/kr/{date}/fallback/{rid}.json", json.dumps({"run_id": rid}))
    for path, text in (raw or {}).items():
        F.write(repo, path, text)
    if market_data is not None:
        F.write(repo, "kr/data/kr_market_data.json", json.dumps(market_data))
    F.commit(repo, "data")
    return str(repo)


def notes(root, seen=None):
    lines, keys = D.kr_check_notes(root, rev="HEAD", seen=seen or {})
    assert D.safe_notes(lines) == lines          # 줄 모양이 허용 목록 밖이면 「기타 안내」로 뭉개진다
    return lines, keys


def test_clean_runs_give_no_lines(tmp_path):
    root = repo_with(tmp_path, runs=[(DAY, "r1", manifest(checks()))])
    assert notes(root) == ([], [])


def test_mismatch_line_names_both_numbers_and_that_blocking_is_off(tmp_path):
    k = {"status": "mismatch", "naver_pct": -1.22, "derived_pct": 0.35, "cross_note": False}
    root = repo_with(tmp_path, runs=[(DAY, "r1", manifest(checks(ip(kosdaq=k))))])
    lines, keys = notes(root)
    assert lines == ["KR 11/12 코스닥 등락률: 네이버 -1.22% vs 종가로 계산 +0.35% — 같은 응답 안에서 어긋남"
                     "(기록만, 차단 꺼짐)"]
    assert [k for k, _ in keys] == [f"{DAY}|index_pct.KOSDAQ|mismatch"]


def test_mismatch_in_block_mode_says_publish_stopped(tmp_path):
    k = {"status": "mismatch", "naver_pct": -1.22, "derived_pct": 0.35}
    root = repo_with(tmp_path, runs=[(DAY, "r1", manifest(checks(ip(kosdaq=k, mode="block"))))])
    assert "발행 멈춤" in notes(root)[0][0]


def test_blocking_statuses_have_fixed_reasons(tmp_path):
    runs = []
    for i, st in enumerate(["ratio_missing", "unverified", "flat_unverified", "flat_contradicted", "fetch_error"]):
        runs.append((DAY, f"r{i}", manifest(checks(ip(kosdaq={"status": st})))))
    root = repo_with(tmp_path, runs=runs)
    lines, _ = notes(root)
    assert len(lines) == 5
    assert all(l.startswith("KR 11/12 코스닥 등락률: ") and l.endswith("발행 멈춤") for l in lines)
    assert any("보합" in l for l in lines)


def test_unknown_status_is_one_word(tmp_path):
    root = repo_with(tmp_path, runs=[(DAY, "r1", manifest(checks(ip(kosdaq={"status": "<script>" * 50}))))])
    lines, _ = notes(root)
    assert lines == ["KR 11/12 코스닥 등락률: 알 수 없는 상태 — 맥에서 확인"]


def test_cross_note_line(tmp_path):
    k = {"status": "ok", "naver_pct": -0.61, "derived_pct": -0.607, "cross_note": True}
    root = repo_with(tmp_path, runs=[(DAY, "r1", manifest(checks(ip(kospi=k))))])
    assert notes(root)[0] == ["KR 11/12 코스피 등락률: 전일 종가가 두 응답에서 어긋남(같은 응답 안 계산은 일치) — 기록만"]


def test_flows_lines(tmp_path):
    fl = {"KOSPI": {"state": "blocked", "faults": [{"date": DAY, "status": "partial", "fields": ["foreign"]}]},
          "KOSDAQ": {"state": "ok", "faults": [{"date": "2026-11-10", "status": "unreadable",
                                                "fields": ["individual", "foreign", "institution"]}]}}
    root = repo_with(tmp_path, runs=[(DAY, "r1", manifest(checks(flows=fl)))])
    lines, _ = notes(root)
    assert "KR 11/12 코스피 수급: 외국인 값을 못 읽음(당일) — 수급 결측으로 발행 멈춤" in lines
    assert "KR 11/12 코스닥 수급: 11/10 개인·외국인·기관 값을 못 읽음 — 그 날만 주간 집계에서 빠짐(기록만)" in lines


def test_flows_error_and_top_value_lines(tmp_path):
    fl = {"KOSPI": {"state": "error", "faults": []}, "KOSDAQ": {"state": "ok", "faults": []}}
    root = repo_with(tmp_path, runs=[
        (DAY, "r1", manifest(checks(flows=fl, top={"error": "거래대금 시총 상위 100행 중 …"}))),
        (DAY, "r2", manifest(checks(top={"rows": 950, "dash": 200, "bad": 0, "dash_top100": 0, "positive_rows": 9})))])
    lines, _ = notes(root)
    assert "KR 11/12 코스피 수급: 요청 실패 — 수급 결측으로 발행 멈춤" in lines
    assert "KR 11/12 거래대금: 수집 실패 — 거래대금 결측으로 발행 멈춤" in lines
    assert "KR 11/12 거래대금: 상위 표의 양수 행이 10개 미만 — 거래대금 결측으로 발행 멈춤" in lines
    assert "KR 11/12 거래대금: 빈 값(-) 비율 21% — 부분 장애일 수 있음(기록만)" in lines


def test_config_status_line(tmp_path):
    root = repo_with(tmp_path, runs=[(DAY, "r1", manifest(checks(ip(mode="block", cfg="invalid_block"))))])
    assert notes(root)[0] == ["KR 11/12 등락률 검증 설정: 설정을 읽지 못함 — 차단(block)으로 읽음"]


def test_every_line_survives_the_note_whitelist(tmp_path):
    fl = {"KOSPI": {"state": "blocked", "faults": [{"date": DAY, "status": "partial", "fields": ["foreign"]}]},
          "KOSDAQ": {"state": "error", "faults": []}}
    k = {"status": "mismatch", "naver_pct": -1.22, "derived_pct": 0.35, "cross_note": True}
    root = repo_with(tmp_path, runs=[(DAY, "r1", manifest(checks(ip(kosdaq=k, cfg="missing_default"), fl,
                                                                 {"error": "x"})))],
                     fallbacks=[("2026-11-11", "f1")])
    lines, _ = notes(root)
    lines.append(D.KR_CHECK_UNREAD)
    assert len(lines) >= 6
    assert D.safe_notes(lines) == lines
    # 폴백 보완 자료(kr_market_data.json)가 이 레포에 없어 읽지 못한 줄도 나온다 — 그 줄만 꼭 싣는 줄
    assert all(c == ("must" if n == D.KR_CHECK_UNREAD else "kr") for n, c in D._classified_notes(lines))


def test_dedupe_by_date_item_status(tmp_path):
    k = {"status": "flat_unverified"}
    root = repo_with(tmp_path, runs=[(DAY, "r1", manifest(checks(ip(kosdaq=k)))),
                                     (DAY, "r2", manifest(checks(ip(kosdaq=k))))])
    lines, keys = notes(root)
    assert len(lines) == 1 and len(keys) == 1
    assert notes(root, seen={keys[0][0]: DAY}) == ([], [])


def test_old_manifests_without_checks_are_skipped(tmp_path):
    root = repo_with(tmp_path, runs=[(DAY, "r1", manifest(None))])
    assert notes(root) == ([], [])


def test_only_the_last_three_trade_day_folders(tmp_path):
    k = {"status": "ratio_missing"}
    runs = [(d, "r1", manifest(checks(ip(kosdaq=k)), date=d))
            for d in ("2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11")]
    root = repo_with(tmp_path, runs=runs, raw={"versions/kr/2026-11-12/published/published.json": "{}"})
    lines, _ = notes(root)
    assert [l[3:8] for l in lines] == ["11/09", "11/10", "11/11"]


def test_fallback_only_day_reads_market_data(tmp_path):
    md = {"report_date": "2026-11-11", "complete": False,
          "checks": checks(ip(kosdaq={"status": "ratio_missing"}))}
    root = repo_with(tmp_path, fallbacks=[("2026-11-11", "f1"), ("2026-11-11", "f2")], market_data=md)
    lines, _ = notes(root)
    assert "KR 11/11 판 기록 없이 올라간 수집 2건" in lines
    assert any(l.startswith("KR 11/11 코스닥 등락률:") for l in lines)


def test_fallback_day_with_other_market_data_date_is_not_supplemented(tmp_path):
    md = {"report_date": "2026-11-12", "checks": checks(ip(kosdaq={"status": "ratio_missing"}))}
    root = repo_with(tmp_path, fallbacks=[("2026-11-11", "f1")], market_data=md)
    assert notes(root)[0] == ["KR 11/11 판 기록 없이 올라간 수집 1건"]


def test_git_failure_is_one_line(tmp_path):
    lines, keys = D.kr_check_notes(str(tmp_path), rev="HEAD", seen={})
    assert lines == [D.KR_CHECK_UNREAD] and keys == []


def test_broken_manifest_is_one_line(tmp_path):
    root = repo_with(tmp_path, raw={f"versions/kr/{DAY}/runs/r1/manifest.json": "{broken"})
    assert notes(root)[0] == [D.KR_CHECK_UNREAD]


def test_one_broken_manifest_does_not_hide_other_lines(tmp_path):
    k = {"status": "ratio_missing"}
    root = repo_with(tmp_path, runs=[(DAY, "r2", manifest(checks(ip(kosdaq=k)))),
                                     (DAY, "r3", manifest({"error": "unreadable"}))],
                     raw={f"versions/kr/{DAY}/runs/r1/manifest.json": "{broken"})
    lines, _ = notes(root)
    assert lines[0] == D.KR_CHECK_UNREAD and lines.count(D.KR_CHECK_UNREAD) == 1
    assert any(l.startswith("KR 11/12 코스닥 등락률:") for l in lines)


def test_first_run_record_survives_a_clean_rerun(tmp_path):
    # 1차 cross_note + 수급 partial → 2차 정상 재수집이 고정 경로를 덮어도 1차 manifest 로 줄과 보고 행이 나온다
    k = {"status": "ok", "naver_pct": -0.61, "derived_pct": -0.607, "cross_note": True}
    fl = {"KOSPI": {"state": "ok", "faults": [{"date": "2026-11-10", "status": "partial", "fields": ["institution"]}]},
          "KOSDAQ": {"state": "ok", "faults": []}}
    root = repo_with(tmp_path, runs=[(DAY, "20261112T0800Z-gh1.1", manifest(checks(ip(kospi=k), fl))),
                                     (DAY, "20261112T0830Z-gh2.1", manifest(checks()))],
                     market_data={"report_date": DAY, "complete": True, "checks": checks()})
    lines, _ = notes(root)
    assert any("전일 종가가 두 응답에서 어긋남" in l for l in lines)
    assert any("11/10 기관 값을 못 읽음" in l for l in lines)
    rows = IC.report_rows(IC.run_manifests(root, "HEAD"))
    assert [r["KOSPI_cross_note"] for r in rows] == [True, False]
    assert IC.summary(rows)["mismatch_or_cross_note_days"] == [DAY]


def test_report_cli_reads_runs(tmp_path, capsys):
    k = {"status": "mismatch", "naver_pct": 1.0, "derived_pct": 0.5}
    root = repo_with(tmp_path, runs=[(DAY, "r1", manifest(checks(ip(kosdaq=k)))), (DAY, "r0", manifest(None))])
    assert IC.main(["--report", "--root", root, "--rev", "HEAD"]) == 0
    out = capsys.readouterr().out
    assert "mismatch" in out and "실행 1" in out


def test_report_counts_only_days_with_both_indices_checked(tmp_path):
    # 구현 검토 1회 #3 — 읽지 못한 검사는 관찰 일수가 아니다(block 전환 근거가 부풀면 안 된다)
    days = [f"2026-10-{d:02d}" for d in (20, 21, 22, 23, 24, 27, 28, 29, 30)]
    runs = [(d, "r1", manifest(checks(), date=d)) for d in days]
    runs.append(("2026-10-31", "r1", manifest({"error": "unreadable"}, date="2026-10-31")))
    runs.append(("2026-11-02", "r1", manifest(checks(ip(kosdaq={"status": "fetch_error"})), date="2026-11-02")))
    root = repo_with(tmp_path, runs=runs, raw={"versions/kr/2026-11-03/runs/r1/manifest.json": "{broken"})
    s = IC.summary(IC.report_rows(IC.run_manifests(root, "HEAD")))
    assert s["trade_days"] == 9
    assert s["unreadable_days"] == ["2026-10-31", "2026-11-02", "2026-11-03"]


def test_report_cli_shows_unreadable_days(tmp_path, capsys):
    root = repo_with(tmp_path, runs=[(DAY, "r1", manifest({"error": "unreadable"}))])
    assert IC.main(["--report", "--root", root, "--rev", "HEAD"]) == 0
    out = capsys.readouterr().out
    assert "관찰 거래일 0" in out and "읽지 못한 날 1" in out and DAY in out


def test_fallback_market_data_unreadable_keeps_other_lines(tmp_path):
    # 구현 검토 1회 #4 — 보완 자료를 못 읽은 사실도, 앞서 읽은 다른 실행의 경고도 남긴다
    k = {"status": "mismatch", "naver_pct": -1.22, "derived_pct": 0.35}
    root = repo_with(tmp_path, runs=[(DAY, "r1", manifest(checks(ip(kosdaq=k))))],
                     fallbacks=[("2026-11-11", "f1")])                     # kr_market_data.json 없음
    lines, _ = notes(root)
    assert D.KR_CHECK_UNREAD in lines
    assert "KR 11/11 판 기록 없이 올라간 수집 1건" in lines
    assert any(l.startswith("KR 11/12 코스닥 등락률: 네이버") for l in lines)


def test_fallback_market_data_broken_keeps_other_lines(tmp_path):
    k = {"status": "mismatch", "naver_pct": -1.22, "derived_pct": 0.35}
    root = repo_with(tmp_path, runs=[(DAY, "r1", manifest(checks(ip(kosdaq=k))))],
                     fallbacks=[("2026-11-11", "f1")], raw={"kr/data/kr_market_data.json": "{broken"})
    lines, _ = notes(root)
    assert D.KR_CHECK_UNREAD in lines and lines.count(D.KR_CHECK_UNREAD) == 1
    assert "KR 11/11 판 기록 없이 올라간 수집 1건" in lines
    assert any(l.startswith("KR 11/12 코스닥 등락률: 네이버") for l in lines)


def test_report_cli_read_failure(tmp_path, capsys):
    assert IC.main(["--report", "--root", str(tmp_path), "--rev", "HEAD"]) == 1


# ── 접수 뒤에만 기억, 14일 정리 ──────────────────────────────────────────

def test_seen_keys_are_written_only_on_acceptance_and_pruned():
    now = datetime(2026, 11, 13, 9, 5, tzinfo=KST)
    state = {"kr_checks_seen": {"2026-10-20|top_value|error": "2026-10-20", "2026-11-11|flows.KOSPI|blocked": "2026-11-11"},
             "pending": {"id": "2026-11-13:morning-digest:v1", "date": "2026-11-13", "v": 1, "text": "t",
                         "base": {}, "tries": [], "kr_checks": [f"{DAY}|index_pct.KOSDAQ|mismatch"]}}
    D.mark_accepted(state, now)
    assert state["kr_checks_seen"] == {"2026-11-11|flows.KOSPI|blocked": "2026-11-11",
                                       f"{DAY}|index_pct.KOSDAQ|mismatch": "2026-11-13"}


def test_attempt_that_is_not_accepted_does_not_remember():
    now = datetime(2026, 11, 13, 9, 5, tzinfo=KST)
    state = {"pending": {"id": "2026-11-13:morning-digest:v1", "date": "2026-11-13", "v": 1, "text": "t",
                         "base": {}, "tries": [], "kr_checks": ["k"]}}
    D.attempt(state, now, lambda s: None, lambda body, sid: "server")
    assert "kr_checks_seen" not in state


def test_keys_ride_only_for_lines_in_the_text():
    keys = [("a", "KR 11/12 거래대금: 수집 실패 — 거래대금 결측으로 발행 멈춤"), ("b", "KR 11/12 없는 줄")]
    assert D.surviving_kr_keys(keys, "머리\n⚠ KR 11/12 거래대금: 수집 실패 — 거래대금 결측으로 발행 멈춤\n끝") == ["a"]


# ── 당일 미발행 감시 줄 ──────────────────────────────────────────────────

def _note(tmp_path, body):
    repo = F.init(tmp_path)
    F.write(repo, "kr/data/kr_market_data.json", json.dumps(body))
    c = F.commit(repo, "kr data")
    return W._collection_note(str(repo), c, "kr", DAY)


def test_collection_note_names_missing_tokens_and_reasons(tmp_path):
    fl = {"KOSPI": {"state": "ok", "faults": []}, "KOSDAQ": {"state": "blocked", "faults": []}}
    body = {"report_date": DAY, "complete": False, "missing": ["indices", "flows", "flows_intraday"],
            "checks": checks(ip(kosdaq={"status": "flat_unverified"}), fl)}
    note = _note(tmp_path, body)
    assert note.startswith("원인: 확정하지 못했어요") and "완전하지 않아요" in note
    assert "빠진 코어: 지수·수급" in note
    assert "코스닥 등락률 — 보합(0.00%)을 확인하지 못함" in note
    assert "코스닥 수급 — 최신 날짜 수급을 못 읽음" in note
    assert len(note) < 600


def test_collection_note_unknown_values_are_one_word(tmp_path):
    body = {"report_date": DAY, "complete": False, "missing": ["indices", "x" * 500],
            "checks": checks(ip(kosdaq={"status": "y" * 500}))}
    note = _note(tmp_path, body)
    assert "x" * 20 not in note and "y" * 20 not in note
    assert "알 수 없는 상태" in note


def test_cli_remembers_kr_lines_after_acceptance(tmp_path, monkeypatch):
    # 접수된 요약의 줄만 기억하고, 다음 날 같은 줄은 다시 내지 않는다
    import verify_digest as VD
    from review.tests.test_digest import FakeWorker, at, post
    st = str(tmp_path / "st" / "state.json")
    clock = {"now": at(2026, 11, 13, 9, 20)}
    w = FakeWorker()
    w.clock = clock
    line = "KR 11/12 거래대금: 수집 실패 — 거래대금 결측으로 발행 멈춤"
    key = f"{DAY}|top_value|error"

    def fake_build(state, now, args, notes):
        if key not in (state.get("kr_checks_seen") or {}):
            notes.append(line)
            VD.KR_KEYS.append((key, line))
        return [post()], {}, {"posts/2026-11-06.html": "s1"}
    monkeypatch.setenv(D.STATE_ENV, st)
    monkeypatch.setattr(D, "now_kst", lambda: clock["now"])
    monkeypatch.setattr(VD, "build", fake_build)
    monkeypatch.setattr(D, "publish_tail", lambda root, now, fetch=True: [])
    real_post, real_status = D.post_digest, D.fetch_status
    monkeypatch.setattr(D, "post_digest", lambda body, sid: real_post(body, sid, run=w))
    monkeypatch.setattr(D, "fetch_status", lambda sid=None: real_status(sid, run=w))
    assert VD.main([]) == 0
    assert f"⚠ {line}" in json.loads(w.posts[-1])["text"]
    assert D.load_state(st)["kr_checks_seen"] == {key: "2026-11-13"}
    clock["now"] = at(2026, 11, 14, 9, 20)
    assert VD.main([]) == 0
    assert line not in json.loads(w.posts[-1])["text"]


def test_collection_note_without_checks_keeps_todays_text(tmp_path):
    body = {"report_date": DAY, "complete": False}
    note = _note(tmp_path, body)
    assert note == ('원인: 확정하지 못했어요 — 이 세션 수집 데이터가 완전하지 않아요'
                    f'(report_date {DAY}, complete false). 루틴은 불완전한 데이터로는 발행하지 않아요')
