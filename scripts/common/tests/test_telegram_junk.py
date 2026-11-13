"""Summaries that must not be stored or quoted (2026-11-12): the model's refusal or a note about
the task instead of a summary, and the polite register. 실측 4건 + 합쇼체 1건(85건 중).
Design: docs/superpowers/specs/2026-11-12-telegram-news-posts.md"""
import json
import os
import types

import pytest

import fetch_telegram as F
from common import tg_summary
from common.telegram_gate import check

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

REFUSALS = [
    '죄송하지만 링크만으로는 영상의 내용을 확인할 수 없어 요약을 드릴 수 없습니다. 영상 속 발언이나 해설 내용을 텍스트로 붙여 주시면, 전해진 시장 소식과 글쓴이가 제시한 시각을 한 문단으로 정리해 드리겠습니다.',
    '원문은 짧은 댓글 두 줄로, 엔비디아만 빠지고 나머지는 오른 종목이 있었다는 관찰과 전망을 담고 있습니다. 두 견해가 엇갈리는 상황을 정리하면 됩니다.',
    '원문에는 날짜와 해시태그, 링크만 있을 뿐 실제 마감 시황의 내용이 담겨 있지 않습니다.',
    '원문에는 키움 차주 트렌드 자료가 있다는 사실과 자료 링크, 앱 안내만 담겨 있을 뿐 필자의 판단이나 근거, 수치가 전혀 없습니다.',
]
POLITE = '프로브카드 수출금액이 크게 늘었으며, 중량 기준 수출단가도 전월 동기 대비 64.0% 올랐다는 점이 함께 제시됐습니다. 이를 근거로 고부가 제품 비중이 커졌다는 시각이 나왔다.'
GOOD = [
    '필자는 나스닥 급락의 원인을 금리보다 AI 투자 속도에 대한 의심에서 찾는다. 단기 반등을 노리기보다 실적으로 투자 회수 속도가 확인될 때까지 기다리는 편이 낫다고 진단했다.',
    '이번 조정은 추세 전환이 아니다. 수요가 꺾인 것은 아니라는 시각이 제시됐다.',                      # 「아니다」 is not polite
    '인트레이터 CEO는 "매도 계획을 보류하겠습니다"라고 말했다는 소식이 전해졌다.',                      # quoted speech
    'AI 인프라 수요. 반도체 수요가 늘었다는 시각이다.',                                               # 「수요」 is a noun
    '원문 기사에 따르면 알파벳이 채권 발행을 검토 중이라는 소식이 전해졌다.',
    'CEO는 주주들에게 죄송하다고 밝혔고 배당 확대를 약속했다는 소식이 전해졌다.',                    # a reported apology
]


@pytest.mark.parametrize('text', REFUSALS)
def test_refusal_and_task_notes_are_unusable(text):
    assert tg_summary.refusal(text)
    assert tg_summary.unusable(text)


def test_polite_register_is_unusable_but_not_a_refusal():
    assert not tg_summary.refusal(POLITE)
    assert tg_summary.polite(POLITE) and tg_summary.unusable(POLITE)


@pytest.mark.parametrize('text', GOOD)
def test_plain_summaries_pass(text):
    assert tg_summary.unusable(text) is None


MEASURED = ['data/telegram/2026-11-06.json', 'data/telegram/2026-11-09.json', 'data/telegram/2026-11-10.json',
            'data/telegram/2026-11-11.json', 'kr/data/telegram/2026-11-06.json', 'kr/data/telegram/2026-11-09.json',
            'kr/data/telegram/2026-11-10.json', 'kr/data/telegram/2026-11-11.json', 'kr/data/telegram/2026-11-12.json']


def test_the_nine_files_measured_on_1112_flag_only_the_known_five():
    """The 85 summaries in the nine files that existed when the rule was written — it must not
    reject a usable one. Named files only: a later day written by the old collector may well hold
    another refusal, and that must not turn this test red."""
    flagged, n = set(), 0
    for rel in MEASURED:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            pytest.skip(f'{rel} 이 이 체크아웃에 없다')
        with open(path, encoding='utf-8') as f:
            for it in json.load(f).get('items', []):
                if it.get('summary_ko'):
                    n += 1
                    if tg_summary.unusable(it['summary_ko']):
                        flagged.add(it['id'])
    assert n == 85
    assert flagged == {'kwusa/61691', 'kwusa/61694', 'kwusa/61756', 'FastStockNews/127732', 'FastStockNews/127813'}


# ── summariser ───────────────────────────────────────────────────────────

class FakeClient:
    def __init__(self, texts):
        self.texts, self.calls = list(texts), 0
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        t = self.texts.pop(0)
        return types.SimpleNamespace(stop_reason='end_turn', content=[types.SimpleNamespace(type='text', text=t)])


BODY = '키움 메모: 반도체 재고 조정 마무리 국면. 업황 저점 통과 판단. ' * 30


def test_short_summary_retries_once_then_fails_on_a_refusal(monkeypatch):
    monkeypatch.setattr(tg_summary.ns, '_text', lambda r: r.content[0].text)
    items = [{'id': 'k/1', 'kind': 'opinion'}, {'id': 'k/2', 'kind': 'opinion'}]
    client = FakeClient([REFUSALS[0], GOOD[0], REFUSALS[1], POLITE])
    done, failed = tg_summary.summarize(items, {'k/1': BODY, 'k/2': BODY}, client=client, model='m', log=lambda *a: None)
    assert items[0]['summary_ko'] == GOOD[0]
    assert 'summary_ko' not in items[1] and items[1]['summary_note'].startswith('합쇼체')
    assert (done, failed) == (1, 1) and client.calls == 4


def test_report_summary_is_checked_too(monkeypatch):
    answers = [(REFUSALS[2], None), (GOOD[4], None), (POLITE, None), (POLITE, None)]
    monkeypatch.setattr(tg_summary.ns, 'summarize_one', lambda *a, **k: answers.pop(0))
    items = [{'id': 'r/1', 'kind': 'report', 'source': {'name': '로이터'}},
             {'id': 'r/2', 'kind': 'report', 'source': {'name': '로이터'}}]
    done, failed = tg_summary.summarize(items, {'r/1': 'Alphabet weighs bonds. ' * 40, 'r/2': 'x ' * 400},
                                        client=object(), model='m', log=lambda *a: None)
    assert items[0]['summary_ko'] == GOOD[4]
    assert 'summary_ko' not in items[1] and items[1]['summary_note'].startswith('합쇼체')
    assert (done, failed) == (1, 1) and not answers


# ── carry-over on re-collection ──────────────────────────────────────────

def test_carry_over_skips_an_unusable_old_summary():
    old = {'a/1': {'id': 'a/1', 'kind': 'opinion', 'source': None, 'summary_ko': REFUSALS[0]},
           'a/2': {'id': 'a/2', 'kind': 'opinion', 'source': None, 'summary_ko': GOOD[0]}}
    items = [{'id': 'a/1', 'kind': 'opinion', 'source': None, 'summary_note': 'x'},
             {'id': 'a/2', 'kind': 'opinion', 'source': None, 'summary_note': 'x'},
             {'id': 'a/3', 'kind': 'opinion', 'source': None}]
    F.carry_summaries(items, old)
    assert 'summary_ko' not in items[0] and items[0]['summary_note'] == 'x'
    assert items[1]['summary_ko'] == GOOD[0] and 'summary_note' not in items[1]
    assert 'summary_ko' not in items[2]


def test_frozen_is_untouched_by_the_junk_rule(tmp_path):
    """A published day's file stays frozen even when one stored summary is a refusal — it is not
    healed automatically; the gate stops it from being quoted."""
    p = tmp_path / '2026-11-11.json'
    p.write_text(json.dumps({'channels': {'c': {'status': 'ok'}}, 'items': [{'id': 'a/1', 'summary_ko': REFUSALS[0]}]}))
    assert F.frozen(str(p))


# ── gate ─────────────────────────────────────────────────────────────────

def test_gate_blocks_quoting_an_item_whose_summary_is_a_refusal():
    data = {'report_date': '2026-11-11', 'items': [
        {'id': 'kwusa/61756', 'kind': 'opinion', 'firm': None, 'analyst': None, 'source': None, 'summary_ko': REFUSALS[0]}]}
    html = ('<html><body><main><p><span data-tg="kwusa/61756">영상의 내용을 확인할 수 없어 요약을 드릴 수 없다는 '
            '의견도 나왔다.</span></p></main></body></html>')
    v = check(html, data)
    assert any('kwusa/61756' in x and '요약이 아니다' in x for x in v), v


def test_gate_does_not_block_a_polite_summary():
    data = {'report_date': '2026-11-11', 'items': [
        {'id': 'FastStockNews/127732', 'kind': 'opinion', 'firm': None, 'analyst': None, 'source': None, 'summary_ko': POLITE}]}
    html = ('<html><body><main><p><span data-tg="FastStockNews/127732">프로브카드 수출금액이 크게 늘었고 중량 기준 수출단가도 '
            '전월 동기 대비 64.0% 올랐다는 시각이 나왔다.</span></p></main></body></html>')
    assert check(html, data) == []
