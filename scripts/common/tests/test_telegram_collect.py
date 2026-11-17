"""telegram/<D>.json 의 collect 칸(2026-11-17) — 채널을 다 읽었을 때만 「글 없음」 확인."""
import fetch_telegram as F

RD = '2026-11-16'


def payload(chans=None, items=(), stats=None):
    return {'report_date': RD, 'channels': chans if chans is not None else {'a': {'status': 'ok'}, 'b': {'status': 'ok'}},
            'items': list(items), 'stats': stats or {'summarized': len(items), 'summary_failed': 0}}


def test_all_read_with_items_is_has_data():
    c = F.telegram_collect(payload(items=[{'id': 1}]))
    assert c['status'] == 'ok' and c['empty'] == 'has_data' and c['as_of'] == RD


def test_all_read_without_items_is_confirmed_none():
    c = F.telegram_collect(payload())
    assert c['status'] == 'ok' and c['empty'] == 'confirmed_none'


def test_failed_or_holed_channel_is_partial_unknown():
    c = F.telegram_collect(payload(chans={'a': {'status': 'failed'}, 'b': {'status': 'ok', 'hole': [1, 9]}}))
    assert c['status'] == 'partial' and c['empty'] == 'unknown'
    assert c['missing'] == ['channel:a:failed', 'hole:b']


def test_every_channel_failed_is_failed():
    c = F.telegram_collect(payload(chans={'a': {'status': 'failed'}}))
    assert c['status'] == 'failed'


def test_items_without_any_summary_is_failed():
    c = F.telegram_collect(payload(items=[{'id': 1}], stats={'summarized': 0, 'summary_failed': 1}))
    assert c['status'] == 'failed' and 'summary:all' in c['missing']


def test_some_summary_failures_only_in_detail():
    c = F.telegram_collect(payload(items=[{'id': 1}, {'id': 2}], stats={'summarized': 1, 'summary_failed': 1}))
    assert c['status'] == 'ok' and '1' in c['detail']


def test_first_save_before_summaries_is_failed():
    assert F.telegram_collect(payload(), final=False)['status'] == 'failed'
