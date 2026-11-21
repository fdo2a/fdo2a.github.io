"""일본 일간 v2 게이트 — 생성 요소 바이트 대조·작성자 금지 글자·우회 시험·다섯 게이트 (설계 §5·§11-6·§11-8·§11-11)."""
import copy
import json

import pytest

from japan import daily_facts as FX
from japan import daily_gate as G
from japan import daily_news_gate as NG
from japan import daily_render as R
from japan.tests import jpx_fixture as F
from japan.tests.test_daily_facts import JGB, P, S, index_from, snap as facts_snap
from japan.tests.test_daily_v2_render import v2
from us import readability as RD
from us import style as ST
from us.news_expand import expand

PAD = ('이 문장은 시험용으로 지어낸 요약이며 수집 요약의 최소 길이를 채우려고 덧붙인 설명이다. ' * 7).strip()
NEWS = {'report_date': S, 'items': [
    {'guid': 'g1', 'category': 'market', 'source': 'ロイター', 'url': 'https://jp.reuters.com/x',
     'published': f'{S}T10:00:00+09:00', 'title': '日経平均は反発、半導体株に買い',
     'summary_ko': '도쿄 증시에서 반도체 관련주에 매수가 몰리며 닛케이 평균이 반등했다. ' + PAD},
    {'guid': 'g2', 'category': 'market', 'source': 'ロイター', 'url': 'https://jp.reuters.com/y',
     'published': f'{S}T11:00:00+09:00', 'title': 'TOPIX 最高値を更新',
     'summary_ko': '도쿄 증시의 대표 지수가 장중 최고치를 다시 썼다. ' + PAD},
    {'guid': 'g3', 'category': 'macro', 'source': 'ロイター', 'url': 'https://jp.reuters.com/z',
     'published': f'{S}T12:00:00+09:00', 'title': '10月の訪日客、過去最多',
     'summary_ko': '10월 방일 외국인 수가 같은 달 기준 역대 최대를 기록했다. ' + PAD},
]}

PROSE = {
    'comment': '<p>닛케이 225 는 <span data-ref="indices.nikkei.value">59,024.28</span> 로 '
               '<span data-ref="indices.nikkei.chg_pct">0.28%</span> 올랐다. 넓은 시장은 약했다.</p>',
    'today': '<p>오후 들어 대형 수출주에만 매수가 몰렸다.</p>',
    'equity': '<p>반등이 넓지 않았다.</p>',
    'bonds': '<p>JGB 10년 금리는 <span data-ref="jgb.10Y.value">2.876%</span> 다.</p>',
    'yen': '<p>달러/엔은 <span data-ref="fx.usdjpy.value">155.20</span> 엔이다.</p>',
    'macro': '<p>물가 지표를 기다리는 장이었다.</p>',
    'news': '<!--NEWS:g1|반도체주 매수에 닛케이 반등--><!--NEWS:g3|방일객 역대 최대-->',
    'next': '<p>다음 주 물가 발표가 확인 지점이다.</p>',
}


def body(prose=None, order=R.SECTIONS):
    prose = dict(PROSE, **(prose or {}))
    parts = ['<section class="card headline-card"><h1>엔저 속 대형주만 올랐다</h1><p>넓은 시장은 약했다.</p></section>']
    for s in order:
        gens = ''.join(f'<!--G:{g}-->' for g in R.GEN_PLACEHOLDERS.get(s, ()))
        tables = ''.join(f'<!--T:{t}-->' for t in R.PLACEHOLDERS.get(s, ()))
        parts.append(f'<section class="card" data-section="{s}"><h2>{R.TITLES[s]}</h2>{gens}{prose[s]}{tables}</section>')
    return '\n'.join(parts)


def page(prose=None, d=None, meta=None, typeset=True):
    d = d or v2()
    b = body(prose, R.order((d.get('calendar') or {}).get('event_day')))
    assert R.validate_body(b, R.order((d.get('calendar') or {}).get('event_day')), schema=2) == []
    b, errs = expand(b, NEWS)
    assert errs == []
    h = R.assemble(b, meta or {'title': '엔저 속 대형주만 올랐다', 'summary': '넓은 시장은 약했다.'}, d)
    return RD.enhance_html(h) if typeset else h


def gate(h, d=None, tg=None, pairs=None):
    return G.check(h, d or v2(), S, filename=f'{S}.html', news=NEWS, tg=tg, pairs=pairs)


def five(h, d=None, tg=None, tmp_path=None):
    """다섯 게이트(조판 뒤): 일간·뉴스·읽기 쉬움(FAIL)·문체(fail)·견해(일간 게이트 안)."""
    import check_readability as CR
    out = {'daily': gate(h, d, tg), 'news': NG.check(h, NEWS, S)}
    path = tmp_path / 'p.html'
    path.write_text(h, encoding='utf-8')
    out['readability'] = CR.audit(str(path))[1]
    out['style'] = [f for f in ST.findings(h) if f.get('level', 'fail') == 'fail']
    return out


def _variants():
    from japan.tests.test_daily_v2_render import _cal
    idx = index_from(F.D1118, F.D1117)
    t_bad = copy.deepcopy(idx)
    t_bad['topix'] = {'status': 'invalid', 'why': 'x'}
    t_bad['sectors'] = {'status': 'invalid', 'why': 'x'}
    s_bad = copy.deepcopy(idx)
    s_bad['sectors'] = {'status': 'invalid', 'why': 'x'}
    mof = {k: dict(r, period=P, prev_period='2026-11-16', source='mof') for k, r in JGB.items()}

    def with_facts(**kw):
        d = v2()
        f = facts_snap(**kw)
        d['facts'], d['jgb'] = f['facts'], f['jgb']
        return d
    out = {'normal': v2(), 'topix_invalid': with_facts(index=t_bad), 'sectors_invalid': with_facts(index=s_bad),
           'mof_fallback': with_facts(jgb=mof),
           'calendar_unconfirmed': v2(calendar=_cal(today_missing=['무역통계'], upcoming_missing=['무역통계'])),
           'meeting_only': v2(calendar=_cal(today=[{'date': S, 'kind': 'meeting', 'name_ko': 'BOJ 금융정책결정회의'}]))}
    return out


@pytest.mark.parametrize('name', sorted(_variants()))
def test_six_fixed_snapshots_pass_all_five_gates(name, tmp_path):
    d = _variants()[name]
    prose = None
    if name == 'mof_fallback':
        prose = {'bonds': '<p>11월 17일 기준 JGB 10년 금리는 <span data-ref="jgb.10Y.value">2.876%</span> 다.</p>'}
    h = page(prose, d)
    assert five(h, d, tmp_path=tmp_path) == {'daily': [], 'news': [], 'readability': [], 'style': []}


@pytest.mark.parametrize('name', sorted(_variants()))
def test_typesetting_keeps_generated_bytes(name):
    d = _variants()[name]
    before = page(d=d, typeset=False)
    after = RD.enhance_html(before)
    frags = list(FX.generated(d).values()) + [f for f in R.render_tables(d).values() if f]
    for f in frags:
        assert before.count(f) == 1 and after.count(f) == 1, f[:60]
    assert G.verify_generated(after, d)[0] == []


# ── 우회 시험 (§11-6) ────────────────────────────────────────────────────

def _blocked(h, d=None, needle=None):
    v = gate(h, d)
    assert v, '통과하면 안 된다'
    if needle:
        assert any(needle in m for m in v), v
    return v


def test_changed_generated_number_blocked():
    h = page().replace('2.5bp 확대됐다', '4.56bp 확대됐다')
    _blocked(h, needle='data-gen="curve"')


def test_flipped_direction_word_blocked():
    _blocked(page().replace('2.5bp 확대됐다', '2.5bp 축소됐다'), needle='data-gen="curve"')


def test_generated_element_twice_elsewhere_or_missing_blocked():
    h = page()
    g = FX.generated(v2())['topix']
    _blocked(h.replace(g, g + g, 1), needle='2번')
    moved = h.replace(g, '', 1).replace('<h2>오늘의 장</h2>', '<h2>오늘의 장</h2>' + g, 1)
    _blocked(moved, needle='equity 절의 바로 아래')
    _blocked(h.replace(g, '', 1), needle='0번')
    _blocked(h.replace(g, '<div>' + g + '</div>', 1), needle='바로 아래')


def test_spread_table_sign_flipped_blocked():
    h = page().replace('<td>+2.5bp</td>', '<td>-2.5bp</td>')
    _blocked(h, needle='코드 표 jgb')


def test_etf_codes_are_invented_numbers_in_v2():
    for code in ('1306', '1617'):
        _blocked(page({'equity': f'<p>업종 ETF({code})는 버텼다.</p>'}), needle=code)


@pytest.mark.parametrize('text', [
    '10-30년 구간은 가팔라졌다.', '11월 17일 자료를 확인했고, 11월 18일 10-30년 구간은 가팔라졌다.',
    '장단기 금리차가 벌어졌다.', '10년과 30년 금리차가 커졌다.', '국채 금리 스프레드가 벌어졌다.',
    'TOPIX는 올랐다.', '토픽스 3,840.02', '17개 업종 가운데 12개가 올랐다.', '오늘은 발표가 없다.',
])
def test_author_prose_banned(text):
    _blocked(page({'today': f'<p>{text}</p>'}))


@pytest.mark.parametrize('text', ['미일 금리차가 확대됐다.', '주가가 가파르게 올랐다.', '플랫폼 기업이 강했다.'])
def test_author_prose_allowed(text):
    assert gate(page({'today': f'<p>{text}</p>'})) == []


def test_banned_words_in_h2_title_caption_blocked():
    _blocked(page({'today': '<h3>TOPIX 약세</h3>'}))
    _blocked(page(meta={'title': 'TOPIX 약세', 'summary': '요약'}))
    _blocked(page(meta={'title': '제목', 'summary': '업종지수가 엇갈렸다'}))
    _blocked(page({'today': '<p class="caption">커브는 평탄했다.</p>'}))


def test_news_section_text_outside_blocks_blocked():
    v = _blocked(page({'news': '<p>TOPIX는 9,999.99로 마감했다.</p><!--NEWS:g1|반도체주 매수에 닛케이 반등-->'}))
    assert any('9999.99' in m or 'TOPIX' in m for m in v)


def test_summary_topix_inside_block_passes():
    """기사 블록 안 수집 요약의 「TOPIX」 는 코드가 찍은 글자다 — 통과."""
    news = copy.deepcopy(NEWS)
    news['items'][0]['summary_ko'] = '도쿄 증시에서 TOPIX가 반등했다. ' + PAD
    b, _ = expand(body(), news)
    h = RD.enhance_html(R.assemble(b, {'title': '제목', 'summary': '요약'}, v2()))
    assert G.check(h, v2(), S, filename=f'{S}.html', news=news) == []


def test_news_title_with_number_not_in_article_blocked():
    v = _blocked(page({'news': '<!--NEWS:g1|TOPIX는 9,999.99로 마감했다-->'}))
    assert any('9999.99' in m for m in v)


def test_news_title_topix_needs_article_field():
    _blocked(page({'news': '<!--NEWS:g1|TOPIX 반등-->'}), needle='TOPIX')
    assert gate(page({'news': '<!--NEWS:g2|TOPIX 최고치-->'})) == []


def test_news_link_sentence_curve_blocked():
    _blocked(page({'news': '<!--NEWS:g1|반도체주 매수에 닛케이 반등|곡선이 가팔라졌다.-->'}), needle='뉴스 블록')


@pytest.mark.parametrize('ref', ['facts.items.0.value', 'curve.s2s10.chg_bp', 'indices.nikkei.denom.value'])
def test_refs_into_facts_curve_denom_blocked(ref):
    _blocked(page({'today': f'<p>값은 <span data-ref="{ref}">1</span> 이다.</p>'}), needle=ref)


@pytest.mark.parametrize('n', ['118.6', '3,824.00', '100.9'])
def test_new_data_numbers_without_ref_are_invented(n):
    _blocked(page({'today': f'<p>그 값은 {n} 이었다.</p>'}))


# ── 날짜 검증 표시 없음 (§11-8) ──────────────────────────────────────────

def test_same_close_two_days_no_date_verified_claim():
    day = dict(F.D1118, Topix=('3,840.02', '0.00', '0.00'))
    d = v2()
    d['facts'] = facts_snap(index_from(day, F.D1117))['facts']
    v = gate(page(d=d), d)
    assert v == [] and not any('날짜 검증' in m for m in v)
    assert FX.items(d)['topix.close']['observation_date'] == S


# ── 견해 요약 겹침 (§11-11, 16회차) ──────────────────────────────────────

def test_views_summary_like_generated_sentence_does_not_block(tmp_path):
    from common import tg_jp
    from japan.tests import test_daily_views as TV
    ch = tg_jp.JP_CHANNEL
    summ = 'TOPIX는 3,824.00으로 전 거래일보다 0.42% 하락했다는 소식이 전해졌다.'
    tg = dict(TV.tg(TV.item(201, summ, dt_utc=f'{S}T01:00:00+00:00')), report_date=S)
    views = (f'<section class="card" data-section="views" data-tg-section><h2>{TV.TG.NEWS_TITLE}</h2>'
             f'<p><span data-tg="{ch}/201">TOPIX는 3,824.00으로 전 거래일보다 0.42% 하락했다는 소식이 전해졌다.</span></p>'
             '</section>')
    b = body()
    news_end = b.index('</section>', b.index('data-section="news"')) + len('</section>')
    b = b[:news_end] + '\n' + views + b[news_end:]
    b, _ = expand(b, NEWS)
    h = RD.enhance_html(R.assemble(b, {'title': '제목', 'summary': '요약'}, v2()))
    assert G.check(h, v2(), S, filename=f'{S}.html', news=NEWS, tg=tg, pairs=[]) == []
    copied = h.replace('<p>반등이 넓지 않았다.</p>', '<p>TOPIX는 3,824.00으로 전 거래일보다 0.42% 하락했다.</p>')
    v = G.check(copied, v2(), S, filename=f'{S}.html', news=NEWS, tg=tg, pairs=[])
    assert v and any('텔레그램' in m or 'TOPIX' in m for m in v)


def test_old_snapshot_path_has_no_v2_checks():
    from japan.tests import test_daily_gate as GH
    assert GH.check(GH.html({'today': '<p>TOPIX는 올랐다.</p>'})) == []


@pytest.mark.parametrize('wrap', ['<!-- {ph} -->', '<!-- {ph}'])
def test_placeholder_inside_another_comment_rejected_at_assembly(wrap):
    for ph in ('<!--G:topix-->', '<!--T:jgb-->'):
        b = body().replace(ph, wrap.format(ph=ph), 1)
        errs = R.validate_body(b, R.SECTIONS, schema=2)
        assert errs, (wrap, ph)


def test_generated_element_inside_comment_blocked_at_gate():
    h = page()
    g = FX.generated(v2())['topix']
    _blocked(h.replace(g, '<!-- ' + g + ' -->', 1), needle='주석 안')
    t = R.render_tables(v2())['jgb']
    _blocked(h.replace(t, '<!-- ' + t + ' -->', 1), needle='코드 표 jgb')


def test_inconsistent_facts_do_not_crash():
    d = v2()
    d['facts']['items'] = [i for i in d['facts']['items'] if not i['field_id'].startswith(('sector.', 'curve.'))]
    assert FX.gen_sectors(d) == '업종별 지수를 확인하지 못해 싣지 않는다.' and R.render_tables(d)['sectors'] == ''
    assert '확인하지 못했다' in FX.gen_curve(d)


def test_writer_section_ids_do_not_double_and_page_passes():
    """2026-11-21 시험 운행: 작성자가 직전 발행본을 본떠 절에 id="read-N" 을 달면 조립이 id 를 하나 더
    붙였고, 부모 검사가 생성 요소를 놓쳐 생성 문장·코드 표를 작성자 글로 보고 63건을 막았다."""
    d = v2()
    b = body(order=R.order((d.get('calendar') or {}).get('event_day')))
    n = 0

    def _writer_id(m):
        nonlocal n
        n += 1
        return f'<section id="read-{n + 5}" class="card" data-section="'
    import re
    b = re.sub(r'<section class="card" data-section="', _writer_id, b)
    assert R.validate_body(b, R.order((d.get('calendar') or {}).get('event_day')), schema=2) == []
    b, errs = expand(b, NEWS)
    assert errs == []
    h = RD.enhance_html(R.assemble(b, {'title': '엔저 속 대형주만 올랐다', 'summary': '넓은 시장은 약했다.'}, d))
    opens = [m.group(0) for m in re.finditer(r'<section\b(?:"[^"]*"|\'[^\']*\'|[^>"\'])*>', h)
             if 'data-section=' in m.group(0)]
    assert len(opens) == len(R.order((d.get('calendar') or {}).get('event_day')))
    for i, tag in enumerate(opens, 1):
        assert re.findall(r'\sid\s*=', tag) == [' id='], tag
        assert f'id="read-{i}"' in tag, tag
    assert gate(h, d) == []


@pytest.mark.parametrize('tag', [
    '<section class="card" data-section="news" title=">" id="read-99">',
    '<section class="card" data-section="news" title=\'info id="read-99" end\'>',
    '<section class="card" data-section="news" id="x">',
    '<section data-section="news" class="card">',
])
def test_v2_section_open_tag_must_be_the_plain_form(tag):
    """절 여는 태그는 이름 하나만 작성자 몫이다 — 다른 속성·따옴표 속 > 는 조립 전에 막는다(codex 수정 검토 1회)."""
    d = v2()
    want = R.order((d.get('calendar') or {}).get('event_day'))
    b = body(order=want).replace('<section class="card" data-section="news">', tag, 1)
    assert any('여는 태그' in e for e in R.validate_body(b, want, schema=2))


BAD_OPENS = [
    '<section class="card" data-section="news" title=">" id="read-99">',          # 따옴표 속 > 가 이름 뒤
    '<section title=">" class="card" data-section="news">',                       # 따옴표 속 > 가 이름 앞
    '<section class="card" data-section="news" title=\'data-section="equity"\'>',  # 값 안의 가짜 이름
    '<section class="card" data-section="news" title="x>',                        # 안 닫힌 따옴표
    '<SECTION class="card" DATA-SECTION="news">',
    '<section class="card" data-section=\'news\'>',
    '<section class="card"\ndata-section="news">',
]


@pytest.mark.parametrize('tag', BAD_OPENS)
def test_v2_assemble_refuses_non_plain_open_tag_without_validation(tag):
    """검사를 거치지 않고 조립을 직접 불러도 여는 태그의 꼬리가 본문 글자로 남지 않는다 — 조립하지 않는다
    (codex 수정 검토 2회 #5: `title=">" id="read-99"` 의 뒷부분이 `<h2>` 앞 텍스트로 남았다)."""
    d = v2()
    want = R.order((d.get('calendar') or {}).get('event_day'))
    b = body(order=want).replace('<section class="card" data-section="news">', tag, 1)
    assert R.validate_body(b, want, schema=2) != []
    with pytest.raises(ValueError):
        R.assemble(b, {'title': '제목', 'summary': '요약'}, d)


def test_v2_data_section_word_only_on_section_open_tags():
    d = v2()
    want = R.order((d.get('calendar') or {}).get('event_day'))
    b = body({'today': '<div data-section="today2"><p>오후 들어 대형 수출주에만 매수가 몰렸다.</p></div>'}, want)
    assert any('data-section 글자' in e for e in R.validate_body(b, want, schema=2))
    with pytest.raises(ValueError):
        R.assemble(b, {'title': '제목', 'summary': '요약'}, d)


def test_writer_instruction_section_examples_pass_the_open_tag_check():
    """작성자 지시문의 절 여는 태그 예시는 전부 검사가 받는 꼴이다(codex 수정 검토 2회 #4: 뉴스 절 예시에
    class="card" 가 빠져 있어 그대로 쓰면 막혔다)."""
    import re
    from pathlib import Path
    md = (Path(__file__).resolve().parents[3] / '.claude/agents/japan-daily-writer.md').read_text(encoding='utf-8')
    tags = [t for t in re.findall(r'<section\b[^>`]*>', md) if 'data-section' in t]
    assert len(tags) >= 4 and len(tags) == len(re.findall(r'data-section=', md))
    for t in tags:
        assert R._plain_open(t.replace('"이름"', '"equity"')) is not None, t
