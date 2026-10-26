"""일본 일간 「일본 경제 뉴스」 — 당일 16:30 JST 컷, 경제 갈래만 (codex 설계 검토 #6·#15)."""
import os

from japan import daily_news_gate as G
from japan import news as N
from japan import news_daily as D

S = '2026-10-27'
SUM = ('일본은행은 이날 단기 정책금리를 동결했다. 우에다 총재는 기자회견에서 임금과 물가의 흐름을 더 확인하겠다고 말했다. '
       '시장은 12월 회의에서 인상 가능성을 놓고 엇갈린 반응을 보였다. 엔화는 회견 뒤 소폭 약세를 보였다. '
       '채권시장에서는 2년물 금리가 하락했다. 은행주는 정책 기대 후퇴로 약세를 보였다. '
       '총재는 하반기 임금 협상 결과와 서비스 물가의 지속성을 판단 근거로 들었다. '
       '일부 위원은 엔화 약세가 수입 물가를 다시 밀어 올릴 위험을 지적했다. '
       '정부는 물가 대책을 담은 보정예산 편성을 서두르고 있다고 밝혔다. '
       '닛케이 평균은 오후 들어 낙폭을 줄였고 수출주는 엔 약세 덕에 강세였다. 거래대금은 전날보다 줄었다.')


def _row(guid, cat, title, published, body=800, summary=SUM, source='ロイター'):
    return {'guid': guid, 'url': f'https://finance.yahoo.co.jp/news/detail/{guid}', 'title': title,
            'source': source, 'published': published, 'category': cat, 'body_chars': body,
            'summary_ko': summary}


def test_retag_moves_only_official_boj_speech_to_macro():
    rows = [{'guid': 'a', 'category': 'insight', 'official': True, 'url': 'https://www.boj.or.jp/en/about/press/koen_2026/ko261027a.htm', 'title': 'x'},
            {'guid': 'b', 'category': 'insight', 'official': True, 'url': 'https://www.nli-research.co.jp/report/x', 'title': 'y'},
            {'guid': 'c', 'category': 'global', 'title': 'z'},
            {'guid': 'd', 'category': 'policy', 'title': 'w'}]
    got = D.retag(rows)
    assert [(r['guid'], r['category']) for r in got] == [('a', 'macro'), ('d', 'policy')]
    assert rows[0]['category'] == 'insight'            # 원본(주간 공용 행)은 그대로


def test_cut_filter_on_list_rows():
    rows = [{'guid': 'a', 'created': '15:10', 'category': 'macro'},
            {'guid': 'b', 'created': '17:05', 'category': 'macro'},
            {'guid': 'c', 'created': '10/26', 'category': 'macro'},
            {'guid': 'd', 'published': f'{S}T16:00:00+09:00', 'category': 'macro'}]
    got = D.cut_filter(rows, S, today=S)
    assert [r['guid'] for r in got] == ['a', 'd']


def test_cut_before_cap():
    rows = [{'guid': str(i), 'created': '18:00', 'category': 'macro', 'title': f'記事{i}'} for i in range(6)]
    rows.append({'guid': 'in', 'created': '09:00', 'category': 'macro', 'title': '日銀'})
    got = N.preselect(D.cut_filter(rows, S, today=S))
    assert [r['guid'] for r in got] == ['in']


def test_finalize_daily_rules():
    rows = [_row('m1', 'macro', '日銀、金利据え置き', f'{S}T12:00:00+09:00'),
            _row('m2', 'macro', '日銀、金利据え置き 植田総裁', f'{S}T13:00:00+09:00'),
            _row('late', 'macro', '円相場 夕方', f'{S}T20:00:00+09:00'),
            _row('old', 'macro', '前日の記事', '2026-10-26T12:00:00+09:00'),
            _row('i1', 'industry', 'トヨタ 決算', f'{S}T11:00:00+09:00'),
            _row('nob', 'policy', '補正予算', f'{S}T11:00:00+09:00', body=0)]
    got = D.finalize_daily(rows, S)
    assert [r['guid'] for r in got] == ['m1', 'i1']


def _html(blocks, title=D.TITLE):
    inner = ''.join(f'<div class="news-item" data-news="{g}"><p>{SUM}</p></div>' for g in blocks)
    return (f'<body data-register="da"><section data-section="news"><h2>{title}</h2>{inner}</section>'
            '</body>')


def _collected(rows):
    return {'report_date': S, 'cut': D.CUT, 'items': rows}


MACRO = [_row(f'm{i}', 'macro', f'日銀 会合 {i}回目', f'{S}T1{i}:00:00+09:00') for i in range(4)]


def test_four_same_category_blocked():
    rows = [_row(f'x{i}', 'macro', t, f'{S}T1{i}:00:00+09:00')
            for i, t in enumerate(['日銀', '補正予算', '賃金統計', '消費支出'])]
    v = G.check(_html([r['guid'] for r in rows]), _collected(rows), S)
    assert any('갈래당' in m for m in v)


def test_same_event_blocked():
    rows = [_row('a', 'macro', '日銀、金利据え置き', f'{S}T12:00:00+09:00'),
            _row('b', 'policy', '日銀、金利据え置き 総裁会見', f'{S}T13:00:00+09:00')]
    v = G.check(_html(['a', 'b']), _collected(rows), S)
    assert any('같은 사건' in m for m in v)


def test_global_item_blocked():
    rows = [_row('g', 'global', '米雇用統計', f'{S}T12:00:00+09:00')]
    v = G.check(_html(['g']), _collected(rows), S)
    assert any('갈래' in m for m in v)


def test_after_cut_blocked():
    rows = [_row('late', 'macro', '円相場', f'{S}T20:00:00+09:00')]
    v = G.check(_html(['late']), _collected(rows), S)
    assert any('16:30' in m for m in v)


def test_previous_day_blocked():
    rows = [_row('old', 'macro', '円相場', '2026-10-26T12:00:00+09:00')]
    v = G.check(_html(['old']), _collected(rows), S)
    assert any('2026-10-26' in m for m in v)


def test_block_outside_news_section_blocked():
    rows = [_row('a', 'macro', '日銀', f'{S}T12:00:00+09:00')]
    html = ('<body data-register="da"><section data-section="equity"><div class="news-item" data-news="a">'
            f'<p>{SUM}</p></div></section><section data-section="news"><h2>{D.TITLE}</h2></section></body>')
    assert any('절 밖' in m for m in G.check(html, _collected(rows), S))


def test_clean_section_passes():
    rows = [_row('a', 'macro', '日銀', f'{S}T12:00:00+09:00')]
    assert G.check(_html(['a']), _collected(rows), S) == []


def test_weekly_freeze_untouched(tmp_path):
    import fetch_japan_news as F
    payload = F.save_daily(str(tmp_path), S, [], complete=True, notes=[])
    assert payload['report_date'] == S and payload['cut'] == D.CUT
    assert os.path.exists(tmp_path / 'news' / 'daily' / f'{S}.json')
    assert not os.path.exists(tmp_path / 'news' / f'{S}.json')


def test_check_news_cli_jp_daily(tmp_path, monkeypatch, capsys):
    import json
    import sys
    import check_news
    d = tmp_path / 'news' / 'daily'
    d.mkdir(parents=True)
    rows = [_row('late', 'macro', '円相場', f'{S}T20:00:00+09:00')]
    (d / f'{S}.json').write_text(json.dumps(_collected(rows), ensure_ascii=False), encoding='utf-8')
    html = tmp_path / 'post.html'
    html.write_text(_html(['late']), encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['check_news.py', '--html', str(html), '--datadir', str(tmp_path),
                                      '--date', S, '--market', 'jp-daily'])
    assert check_news.main() == 1
    assert '16:30' in capsys.readouterr().err
