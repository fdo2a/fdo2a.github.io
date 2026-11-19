"""기사 숫자 목록(2026-11-20) — 숫자만 커밋, 기사별 대조, 요약 ⊂ 본문 섀도."""
import json
import os

from common import article_numbers as AN
from common import numsrc as S


def q(text):
    out = [x for x in S.quantities(text) if not x.code]
    assert len(out) == 1, out
    return out[0]


def test_english_money_scale_and_korean_compound_match():
    nums = AN._norm_list(AN.english_numbers('The company raised $282 million and shares rose 6.5% to 803,000 won.'))
    assert [282000000.0, 'money', 'USD'] in nums
    assert [6.5, 'pct', None] in nums
    assert AN.in_list(q('2억8200만달러'), nums)
    assert AN.in_list(q('6.5%'), nums)
    assert AN.in_list(q('80만 3000원'), nums)


def test_rounding_uses_printed_digits_only_one_way():
    nums = [[2.9, 'pct', None]]
    assert AN.in_list(q('2.9%'), nums)
    assert not AN.in_list(q('2.89%'), nums)          # 글이 기사보다 정밀하면 기사에서 온 숫자가 아니다
    assert AN.in_list(q('3%'), [[2.9, 'pct', None]])  # 반올림은 글의 자리로
    assert not AN.in_list(q('2.9%p'), nums)           # 갈래가 다르다
    assert not AN.in_list(q('2.9달러'), [[2.9, 'money', 'JPY']])   # 통화가 다르다


def test_basis_points_and_percentage_points():
    nums = AN._norm_list(AN.english_numbers('a 25 basis point hike, up 0.3 percentage point, 2x leverage'))
    assert AN.in_list(q('25bp'), nums)
    assert AN.in_list(q('0.3%p'), nums)
    assert AN.in_list(q('2배'), nums)


def test_summary_subset_of_body_check():
    it = AN.build_item('g1', '매출은 6.5% 늘어 2억8200만달러다. 이익은 9.9% 늘었다.', 'Title', 'Sales rose 6.5% to $282 million.')
    assert it['summary_check']['status'] == 'mismatch'
    assert it['summary_check']['missing'] == ['9.9%']
    ok = AN.build_item('g2', '매출은 6.5% 늘었다.', 'T', 'Sales rose 6.5%.')
    assert ok['summary_check'] == {'status': 'ok', 'missing': []}
    nb = AN.build_item('g3', '6.5% 늘었다.', 'Up 6.5%', None)
    assert nb['summary_check']['status'] == 'no_body' and nb['body_numbers'] == []
    assert [6.5, 'pct', None] in nb['title_numbers']


def test_serialized_file_carries_no_article_words(tmp_path):
    body = ('ZZSECRETWORD Plutonium revenue jumped 12.5% to $3.2 billion according to people familiar, '
            'XQWERTY quote "we are thrilled" said the chief.')
    path = tmp_path / 'news' / 'numbers' / '2026-11-20.json'
    n, off = AN.write_day(str(path), '2026-11-20', [('guid-1', '매출이 12.5% 늘었다.', 'Plutonium Corp beats', body)])
    raw = path.read_text(encoding='utf-8')
    for word in ('ZZSECRETWORD', 'Plutonium', 'XQWERTY', 'thrilled', 'familiar', 'chief'):
        assert word not in raw
    d = json.loads(raw)
    assert set(d) == {'report_date', 'extractor', 'items'}
    assert set(d['items'][0]) == set(AN.ITEM_KEYS)
    for e in d['items'][0]['body_numbers']:
        assert isinstance(e[0], float) and e[1] in AN.KINDS and (e[2] is None or e[2] in AN.CURRENCIES)


def test_serialize_drops_foreign_keys_and_free_text():
    bad = {'guid': 'g', 'summary_sha': 'a' * 64, 'title_numbers': [[1.0, 'num', None], [2.0, 'body word', None]],
           'body_numbers': [[3.0, 'pct', 'secret']], 'n': 9, 'body': 'leak', 'summary_check': {'status': 'ok', 'missing': []}}
    out = AN.serialize('2026-11-20', [bad])
    assert 'body' not in out['items'][0]
    assert out['items'][0]['title_numbers'] == [[1.0, 'num', None]]
    assert out['items'][0]['body_numbers'] == [] and out['items'][0]['n'] == 0


def test_lists_for_refuses_mismatched_or_duplicate(tmp_path):
    summ = {'g1': '6.5% 늘었다.', 'g2': '3% 줄었다.', 'g3': '1% 늘었다.'}
    items = [AN.build_item('g1', summ['g1'], '', 'up 6.5%'), AN.build_item('g2', '옛 요약 3% 줄었다', '', 'down 3%'),
             AN.build_item('g3', summ['g3'], '', 'up 1%'), AN.build_item('g3', summ['g3'], '', 'up 1%')]
    got = AN.lists_for(AN.serialize('2026-11-20', items), summ)
    assert got['g1'] and got['g2'] is None and got['g3'] is None
    assert AN.lists_for(None, summ) == {g: None for g in summ}


def test_carry_previous_item_when_body_missing(tmp_path):
    path = str(tmp_path / 'n.json')
    AN.write_day(path, '2026-11-20', [('g1', '6.5% 늘었다.', '', 'up 6.5%')])
    prev = AN.load_prev(path)
    AN.write_day(path, '2026-11-20', [('g1', '6.5% 늘었다.', '', None)], prev)
    d = json.load(open(path))
    assert d['items'][0]['body_numbers'] == [[6.5, 'pct', None]]
    # 요약이 바뀌면 옮기지 않는다
    AN.write_day(path, '2026-11-20', [('g1', '7% 늘었다.', '', None)], AN.load_prev(path))
    assert json.load(open(path))['items'][0]['summary_check']['status'] == 'no_body'


def test_fetch_news_hook_writes_numbers_subdir(tmp_path):
    import fetch_news
    bd = tmp_path / 'bodies'
    bd.mkdir()
    (bd / '01.txt').write_text('Revenue rose 4.4% to $1.2 billion.', encoding='utf-8')
    chosen = [{'guid': 'g1', 'title': 'Revenue up', 'summary_ko': '매출이 4.4% 늘어 12억 달러다.', 'body_file': '01.txt'}]
    fetch_news.write_numbers(str(tmp_path), '2026-11-20', chosen, str(bd))
    p = tmp_path / 'news' / 'numbers' / '2026-11-20.json'
    d = json.loads(p.read_text())
    assert d['items'][0]['summary_check']['status'] == 'ok'
    assert not os.path.exists(tmp_path / 'news' / '2026-11-20.numbers.json')
