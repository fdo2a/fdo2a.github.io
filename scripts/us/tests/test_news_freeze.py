"""뉴스 동결 — 발행 도중 재수집이 요약을 바꿔 완성된 초안을 무효화하던 것을 막는다.

2026-09-26: 09:10 KST 런이 뉴스·산업 브리프까지 게이트를 통과한 뒤 발행 직전 pull 에서
10:08 재수집 커밋을 받았다. 재수집이 모든 기사의 summary_ko 를 새로 만들어 뉴스 게이트가
40건 어긋났고, 고치다 5시간 한도로 죽어 그날 브리프가 나가지 못했다.
"""
import json

import fetch_news as F
from us import news_summary as NS


def _write(tmp_path, items):
    d = tmp_path / 'news'
    d.mkdir()
    p = d / '2026-09-25.json'
    p.write_text(json.dumps({'report_date': '2026-09-25', 'items': items}, ensure_ascii=False))
    return str(p)


def test_a_day_with_summaries_is_frozen(tmp_path):
    p = _write(tmp_path, [{'guid': 'a', 'summary_ko': '요약'}])
    assert F.frozen(p)


def test_a_day_without_any_summary_is_not_frozen(tmp_path):
    # 첫 수집에서 요약이 전부 실패한 날(자격 증명 등)은 다시 받아야 한다.
    p = _write(tmp_path, [{'guid': 'a', 'summary_note': 'WIF 설정 형식 오류'}])
    assert not F.frozen(p)
    assert not F.frozen(str(tmp_path / 'news' / 'none.json'))


def test_refresh_carries_existing_summaries_over_by_guid(tmp_path):
    p = _write(tmp_path, [{'guid': 'a', 'summary_ko': '예전 요약', 'summary_model': 'm'}])
    chosen = [{'guid': 'a', 'title': 't'}, {'guid': 'b', 'title': 'u'}]
    assert F.carry_summaries(p, chosen) == 1
    assert chosen[0]['summary_ko'] == '예전 요약' and 'summary_ko' not in chosen[1]


def test_summarizer_skips_items_that_already_have_a_summary(tmp_path):
    calls = []

    class Fake:
        class messages:
            @staticmethod
            def create(**kw):
                calls.append(kw)
                raise AssertionError('이미 요약된 기사를 다시 요약했다')

    (tmp_path / 'x.txt').write_text('본문')
    items = [{'guid': 'a', 'body_chars': 2, 'body_file': 'x.txt', 'summary_ko': '예전 요약'}]
    assert NS.summarize_items(items, str(tmp_path), model='m', client=Fake, log=lambda *a: None) == 0
    assert items[0]['summary_ko'] == '예전 요약' and not calls
