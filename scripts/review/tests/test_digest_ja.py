"""매일 검증 알림의 일본어판 줄(2026-11-14) — 꼬리 끝에 줄일 수 있는 줄로만 붙고, 꺼져 있거나 실패하면 없다.

spec: docs/superpowers/specs/2026-11-14-japanese-edition.md
"""
import json

import pytest

from review import digest as D


@pytest.fixture
def cli(tmp_path, monkeypatch):
    import verify_digest as VD
    from review.tests.test_digest import FakeWorker, at, post
    w = FakeWorker()
    clock = {"now": at(2026, 11, 14, 9, 20)}
    w.clock = clock
    monkeypatch.setenv(D.STATE_ENV, str(tmp_path / "st" / "state.json"))
    monkeypatch.setattr(D, "now_kst", lambda: clock["now"])
    monkeypatch.setattr(VD, "build", lambda state, now, args, notes: ([post()], {}, {"posts/2026-11-06.html": "s1"}))
    monkeypatch.setattr(D, "publish_tail", lambda root, now, fetch=True: [])
    real_post, real_status = D.post_digest, D.fetch_status
    monkeypatch.setattr(D, "post_digest", lambda body, sid: real_post(body, sid, run=w))
    monkeypatch.setattr(D, "fetch_status", lambda sid=None: real_status(sid, run=w))
    return VD, w


def _text(w):
    return json.loads(w.posts[-1])["text"]


def test_ja_lines_go_in_the_tail(cli, monkeypatch):
    VD, w = cli
    from ja import runner as JR
    lines = ["일본어판 — 지난 하루 발행 2편 · 보류 1편 · 대기 0편",
             "일본어판 보류 news/2026-11-13: 확인 안 된 인명: 가타야마 사쓰키"]
    monkeypatch.setattr(JR, "digest_lines", lambda root, now: list(lines))
    assert VD.main([]) == 0
    text = _text(w)
    assert all(x in text for x in lines)
    assert text.index(lines[0]) < text.index(lines[1]) < text.index(D.CAVEAT)     # 꼬리 끝, 맺음 줄 앞


def test_no_ja_lines_when_off_or_broken(cli, monkeypatch):
    VD, w = cli
    from ja import runner as JR
    monkeypatch.setattr(JR, "digest_lines", lambda root, now: [])
    assert VD.main([]) == 0
    base = _text(w)
    assert "일본어판" not in base

    def boom(root, now):
        raise RuntimeError("깨졌다")
    monkeypatch.setattr(JR, "digest_lines", boom)
    assert VD.main(["--force"]) == 0
    assert "일본어판" not in _text(w)

