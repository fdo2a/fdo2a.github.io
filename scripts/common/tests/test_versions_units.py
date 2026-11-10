"""판 관리 작은 함수들 — 실행 ID·지정 거래일 확인·차이(2026-11-10)."""
import datetime as dt
import json

from common import versions as V

UTC = dt.timezone.utc


def test_run_id_unique_and_carries_attempt():
    now = dt.datetime(2026, 11, 6, 15, 50, tzinfo=UTC)
    assert V.run_id(now, {'GITHUB_RUN_ID': '42', 'GITHUB_RUN_ATTEMPT': '2'}) == '20261106T155000Z-gh42.2'
    a, b = V.run_id(now, {}), V.run_id(now, {})
    assert a != b and '-local-' in a


def _files(peer_date, tech_asof):
    return {'kr/data/kr_session.json': json.dumps({'asia_peers': {'dates': {'닛케이': peer_date, '항셍': peer_date}}}).encode(),
            'kr/data/kr_technical.json': json.dumps({'코스피': {'as_of': tech_asof, 'close': 1.0}}).encode()}


def test_field_status_split_at_exchange_midnight():
    # 00:50 KST = JST 자정 뒤, HKT 자정 전 — 11/06 실측과 같은 경계
    t = dt.datetime(2026, 11, 6, 15, 50, tzinfo=UTC)
    st = V.field_status(_files('2026-11-05', '2026-11-05'), '2026-11-06', t)
    assert st['asia_peers.닛케이'] == 'unverified_target_date'
    assert st['asia_peers.항셍'] == 'stale_or_holiday'
    assert st['technical.코스피'] == 'unverified_target_date'


def test_field_status_ok_in_evening():
    t = dt.datetime(2026, 11, 6, 9, 10, tzinfo=UTC)            # 18:10 KST
    st = V.field_status(_files('2026-11-06', '2026-11-06'), '2026-11-06', t)
    assert st['asia_peers.닛케이'] == 'ok' and st['technical.코스피'] == 'ok'


def test_diff_names_changed_rows():
    a = {'kr/data/kr_industry.json': json.dumps([{'name': 'IT서비스', 'change_pct': 1.15}, {'name': '은행', 'change_pct': -1.74}]).encode()}
    b = {'kr/data/kr_industry.json': json.dumps([{'name': 'IT서비스', 'change_pct': 1.11}, {'name': '은행', 'change_pct': -1.74}]).encode(),
         'kr/data/kr_econ.json': b'{}'}
    d = V.diff_files(a, b)
    assert d['kr/data/kr_industry.json']['rows_changed'] == 1
    assert d['kr/data/kr_industry.json']['examples'] == ['IT서비스']
    assert d['kr/data/kr_econ.json']['class'] == 'filled_in_revision'


def test_post_has_number_forms():
    assert V._post_has_number('<p>코스닥 644.27</p>'.encode(), 644.27)
    assert V._post_has_number('<p>코스피 5,059.69</p>'.encode(), 5059.69)
    assert not V._post_has_number('<p>코스피 5,059.69</p>'.encode(), 644.27)


def test_post_has_number_is_strict():
    assert not V._post_has_number('<p>코스닥 644</p>'.encode(), 644.27)              # 반올림 금지
    assert not V._post_has_number('<p>지수 1644.27</p>'.encode(), 644.27)            # 부분 문자열
    assert not V._post_has_number('<p>x</p><!-- 644.27 -->'.encode(), 644.27)        # 주석
    assert not V._post_has_number('<p data-v="644.27">x</p>'.encode(), 644.27)        # 속성


def test_post_index_value_must_follow_index_name():
    html = '<p>코스피 5,059.69(-6.02%), 코스닥 644.27(-5.03%)</p><p>원·달러 1,644.27원</p>'.encode()
    assert V._post_has_number(html, 644.27, index='KOSDAQ')
    assert not V._post_has_number(html, 5059.69, index='KOSDAQ')
    assert not V._post_has_number(('<p>코스피 5,059.69</p><p>' + 'x' * 60 + ' 644.27</p>').encode(), 644.27, index='KOSDAQ')


def test_post_index_value_rejects_other_index_number():
    html = '<p>코스닥 700.00, 코스피 644.27</p>'.encode()
    assert not V._post_has_number(html, 644.27, index='KOSDAQ')
    assert V._post_has_number(html, 644.27, index='KOSPI')


def test_post_index_value_rejects_other_index_name_between():
    assert not V._post_has_number('<p>코스닥과 코스피 644.27</p>'.encode(), 644.27, index='KOSDAQ')
