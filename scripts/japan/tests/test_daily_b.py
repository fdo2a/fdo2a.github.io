"""일본 일간 B(평소와의 차이) — 실제 레포 자료로 계산·표·생성 문장·작성자 수치 대조 (2026-11-28).

설계 design-drafts/jp-daily-v2/B_design_v6.md §8 완료 기준. 11/24-27 발행본·11/20 후보·씨앗은 바뀌지 않는 과거 자료다.
"""
import copy
import hashlib
import json
import os
import re

import pytest

from build_japan_daily import load_telegram, news_path, snapshot_path
from japan import daily_b as B
from japan import daily_facts as FX
from japan import daily_gate as G
from japan import daily_render as R

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
with open(os.path.join(ROOT, 'data', 'market_holidays.json'), encoding='utf-8') as _fh:
    HD = json.load(_fh)
HOL, _ = B.calendar(HD)

# B 변경 전 코드(40635e56)로 잰 schema 2 발행 스냅샷의 표·조립 해시 — B 항목이 없으면 바이트 그대로다.
GOLDEN_V2 = {
    '2026-11-24': {'indices': 'a92de26635b10b11f70ca93956bfae9058eb34f42fe251fd73f51972e320030b', 'sectors': '7170d92fe3010f6f474bc1c4a63384c0bf974e4fd5a2a9689957e815a3841ae4', 'jgb': '340805af5ef7c809726bd652e8bdbe8b88e0741c1bbe9024a8f9454d56c89138', 'fx': '309d9d5116384358481387df0b246c2695b52350fabea344955bbe8f9f852c18', 'macro': 'a763c8c679cf732e6a194eaa88feef0ec31c172175f0f67ee850b1e0779e29e3', 'next': 'f98a8177ddf36385538c29576da499021f56ec9032004ae12709971122976787', 'assemble': '6a7cbcca5b404fb30b6a7d91fb8e46e76935dddb7a9af958145526fc3674f8c0'},
    '2026-11-25': {'indices': 'e3e4a8e815957c53a24f49ec8a4a51eaa96db6a53c889c97f41a2aafd9607999', 'sectors': '28ff98a1af4fa642f0f1c547cfa68861c028394e79632f656fa300c9405ef93d', 'jgb': '8044d718739af8c29529b9f9a7e19bb088f89d816dbee97754d55108e1c1e47d', 'fx': 'f3870cabef835d7ee034dea98015cd4cbf75b7f84d2f79dd97340ebe879f7b34', 'macro': 'c191472ebb940664d7fb1215176fb8b79b4ecd45ea03a577c2bda4c73f8c9c3b', 'next': 'd5f649b3a69edc0ac9b28b109fece1d794cf0cfcfef47ff2d634a4f4310fd602', 'assemble': 'edac458760c5249caa76e3cd64c00adcf6b15a969d2c5fc8c613e217353c395b'},
    '2026-11-26': {'indices': '06e31be76b23c8ca65f3b39f7949a7d5d89c897d28f5d61412ed46bfd112daba', 'sectors': '2df127b1b31bc0d1d2d7b3029e92930047c62a0cff64ea0c15d9ed802b93e7d8', 'jgb': '1d09f06e9b11c5075ffa79a46cbd6d7206bfc8f163973eee283840c250a91904', 'fx': '361197f70df5b570607eefa3ce4bea923ca23c8b293a6baa280c6ffaf140d58e', 'macro': 'a763c8c679cf732e6a194eaa88feef0ec31c172175f0f67ee850b1e0779e29e3', 'next': '1befc462358002e62aa9746abb98eda11d959552427b0291f005cb6d1c661c93', 'assemble': '21dcd22badbc7d57f87a0d68c112f5c424bf3399838516160c3446e2844f73d7'},
    '2026-11-27': {'indices': '2bd750cbf5852747243a91fea9abc78b8082bf2bf03f8192c31806d79f63089c', 'sectors': '29faa8d8c4ceb5d356c089024d0e1c8ec2bb339c2a898f1c54055347429b9dbf', 'jgb': '350d1f418d7c1f7541b2752cc2e4ad7892fcaed3d22833375d00452d0db8fe44', 'fx': '9d2acacc8f120ad93f096dda962553033c5ed084841c2465d120d4d8b2e6bea3', 'macro': 'c464126add434ec443e0cf11c5c6f649511ac2f2245260daa3e69dd7a3a3c750', 'next': 'f02e2cc1ae1d4294a67962541dc4cf2041b34e0f7e3abb039680b47242e54c43', 'assemble': '7ccc2e109df6d3fbffcb43aebe5b151392d75d4a8d4d0385f119d2be14632659'},
}


def _load(s):
    with open(snapshot_path(ROOT, s), encoding='utf-8') as fh:
        snap = json.load(fh)
    with open(os.path.join(ROOT, 'japan', 'daily', f'{s}.html'), encoding='utf-8') as fh:
        html = fh.read()
    np_ = news_path(ROOT, s)
    news = json.load(open(np_, encoding='utf-8')) if np_.exists() else None
    tg, _ = load_telegram(ROOT, s)
    return html, snap, news, tg


def _with_b(snap, seed=None):
    d = copy.deepcopy(snap)
    items, diag = B.compute(d['session'], d, ROOT, HD, seed=seed)
    d['facts']['items'] += items
    d['facts']['b_diag'] = diag
    return d


def _b_post(s):
    """실제 발행본의 코드 표·생성 문장을 B 를 붙인 스냅샷의 것으로 바꾸고 `usual` 을 주식 절에 넣는다."""
    html, snap, news, tg = _load(s)
    d = _with_b(snap)
    for k, frag in R.render_tables(snap).items():
        if frag:
            assert html.count(frag) == 1
            html = html.replace(frag, R.render_tables(d)[k])
    gen = FX.generated(d)
    old = FX.generated(snap)
    for k in FX.GEN_KINDS:
        html = html.replace(old[k], gen[k])
    html = html.replace(gen['topix'], gen['topix'] + gen['usual'], 1)
    return html, d, news, tg


def _check(html, d, news, tg):
    return G.check(html, d, d['session'], filename=f'{d["session"]}.html', news=news, tg=tg, pairs=[])


def _ins_equity(html, sent):
    m = re.search(r'<section\b[^>]*data-section="equity"[^>]*>', html)
    return html[:m.end()] + '<p>' + sent + '</p>' + html[m.end():]


def _val(d, fid):
    return (B.get(d, fid) or {}).get('value')


# ── 날짜 ───────────────────────────────────────────────────────────────

def test_trading_day_steps_skip_holiday_and_keep_unpublished_session():
    assert B.back('2026-11-27', 5, HOL) == '2026-11-19'      # 11/23 휴장
    assert B.back('2026-11-30', 5, HOL) == '2026-11-20'      # 미발행 11/20 도 거래일
    assert B.back('2026-12-01', 5, HOL) == '2026-11-24'
    assert B.back('2026-12-01', 20, HOL) == '2026-10-30'


# ── 과거 값 원천 ───────────────────────────────────────────────────────

def test_sources_for_each_field():
    h = B.History(ROOT, '2026-11-30', {'session': '2026-11-30'}, HOL)
    assert h.value('2026-11-19', 'topix') == (3822.47, 'denom:2026-11-20')     # 11/19 발행본은 옛 형식(ETF 뿐)
    assert h.value('2026-11-19', 'nikkei')[1] == 'snapshot'
    assert h.value('2026-11-20', 'nikkei') == (56436.65, 'candidate')          # 미발행 세션은 후보
    assert h.value('2026-11-20', 'sector.Topix17Food')[1] == 'candidate'
    v, src = h.value('2026-10-30', 'jgb.2Y')                                    # MOF 폴백 날 → 씨앗의 네이버 값
    assert src == 'seed' and v == 1.881
    assert h.mismatch == []


def test_seed_mismatch_blanks_the_cell_and_says_so():
    with open(os.path.join(ROOT, B.SEED), encoding='utf-8') as fh:
        seed = json.load(fh)
    seed['nikkei']['2026-11-18'] += 1
    _h, snap, _n, _t = _load('2026-11-27')
    d = _with_b(snap, seed=seed)
    assert _val(d, 'b.nikkei.usual') is None                                     # 22개 창에 11/18 이 든다
    assert _val(d, 'b.nikkei.ret5') == -1.23                                    # 5일 끝점(11/19)은 그대로
    assert any('B 원천 불일치 — 2026-11-18 nikkei' in x for x in d['facts']['b_diag'])


def test_out_of_holiday_calendar_makes_every_b_cell_invalid():
    hd = copy.deepcopy(HD)
    hd['jp']['valid_through'] = '2026-11-01'
    items, diag = B.compute('2026-11-27', _load('2026-11-27')[1], ROOT, hd)
    assert items and all(it['status'] == 'invalid' for it in items)
    assert diag and '휴장일 파일 범위 밖' in diag[0]


# ── 11/27 계산값(손 계산과 같다) ────────────────────────────────────────

def test_1127_values_match_hand_calculation():
    _h, snap, _n, _t = _load('2026-11-27')
    d = _with_b(snap)
    assert d['facts']['b_diag'] == []
    assert _val(d, 'b.nikkei.ret5') == round((58711.11 / 59444.21 - 1) * 100, 2) == -1.23
    assert _val(d, 'b.topix.ret5') == round((3815.20 / 3822.47 - 1) * 100, 2)
    assert _val(d, 'b.jgb.2Y.chg5') == -9.0                                     # 1.761 − 1.851
    assert _val(d, 'b.nikkei.usual') == 1.1
    assert _val(d, 'b.sector.Topix17Food.rel5') is not None
    assert _val(d, 'b.sector.Topix17Food.rel20') is None                         # 업종은 11/19 부터
    ends = B.get(d, 'b.nikkei.usual')['ends']
    assert len(ends) == 22 and ends[0]['date'] == '2026-10-27' and ends[-1]['date'] == '2026-11-27'
    assert {'date': '2026-11-20', 'value': 56436.65, 'from': 'candidate'} in ends


# ── 옛 글 회귀 ─────────────────────────────────────────────────────────

def _published():
    return sorted(f[:-5] for f in os.listdir(os.path.join(ROOT, 'japan', 'data', 'daily'))
                  if re.fullmatch(r'\d{4}-\d{2}-\d{2}\.json', f))


@pytest.mark.parametrize('s', _published())
def test_published_snapshots_have_no_b_and_pass_the_gate_as_before(s):
    html, snap, news, tg = _load(s)
    if not B.has_b(snap):
        assert 'usual' not in FX.generated(snap)
    if s in ('2026-11-24', '2026-11-25', '2026-11-26', '2026-11-27'):
        assert _check(html, snap, news, tg) == []


@pytest.mark.parametrize('s', sorted(GOLDEN_V2))
def test_v2_tables_and_assembly_without_b_are_byte_identical(s):
    _h, snap, _n, _t = _load(s)
    got = {k: hashlib.sha256(v.encode()).hexdigest() for k, v in R.render_tables(snap).items()}
    parts = ['<section class="card headline-card"><h1>제목</h1><p>요약</p></section>']
    for sec in R.order(snap['calendar'].get('event_day')):
        g = ''.join(f'<!--G:{x}-->' for x in R.GEN_PLACEHOLDERS.get(sec, ()))
        t = ''.join(f'<!--T:{x}-->' for x in R.PLACEHOLDERS.get(sec, ()))
        parts.append(f'<section class="card" data-section="{sec}"><h2>{R.TITLES[sec]}</h2>{g}<p>본문.</p>{t}</section>')
    got['assemble'] = hashlib.sha256(R.assemble('\n'.join(parts), {'title': 't', 'summary': 's'}, snap).encode()).hexdigest()
    assert got == GOLDEN_V2[s]


# ── B 가 있는 스냅샷: 표·생성 문장·조립 ─────────────────────────────────

def test_b_tables_and_usual_sentence():
    _h, snap, _n, _t = _load('2026-11-27')
    d = _with_b(snap)
    t = R.render_tables(d)
    assert '5거래일' in t['indices'] and '평소 대비' in t['indices'] and '1.1배' in t['indices']
    assert 'TOPIX 대비 5거래일' in t['sectors']
    assert '5거래일 변화' in t['jgb'] and '-9.0bp' in t['jgb']
    usual = FX.generated(d)['usual']
    assert usual.startswith('<p data-gen="usual">TOPIX 하루 등락폭은 직전 20거래일 평균의 약 ')
    assert '닛케이 225는 약 1.1배다.' in usual


def test_usual_empty_when_both_multiples_invalid():
    _h, snap, _n, _t = _load('2026-11-27')
    d = _with_b(snap)
    for it in d['facts']['items']:
        if it['field_id'] in ('b.topix.usual', 'b.nikkei.usual'):
            it.update(status='invalid', value=None)
    assert FX.generated(d)['usual'] == ''
    html, d2, news, tg = _b_post('2026-11-27')
    html = html.replace(FX.generated(d2)['usual'], '', 1)
    for it in d2['facts']['items']:
        if it['field_id'] in ('b.topix.usual', 'b.nikkei.usual'):
            it.update(status='invalid', value=None)
    assert not [x for x in _check(html, d2, news, tg) if 'usual' in x]


def test_usual_placeholder_required_only_with_b():
    body = ('<section class="card headline-card"><h1>t</h1></section>'
            '<section class="card" data-section="equity"><!--G:topix--><!--G:sectors--><!--G:usual--></section>')
    assert any('<!--G:usual-->' in e for e in R.validate_v2(body, b=False))
    assert not any('<!--G:usual-->' in e for e in R.validate_v2(body, b=True))
    body2 = body.replace('<!--G:usual-->', '')
    assert any('<!--G:usual--> 가 0번' in e for e in R.validate_v2(body2, b=True))


# ── 작성자 수치(§5) ────────────────────────────────────────────────────

def test_real_posts_with_b_block_only_the_known_rounded_figure():
    blocked = {}
    for s in ('2026-11-24', '2026-11-25', '2026-11-26', '2026-11-27'):
        blocked[s] = _check(*_b_post(s))
    assert blocked['2026-11-24'] == blocked['2026-11-25'] == blocked['2026-11-26'] == []
    assert len(blocked['2026-11-27']) == 1 and '「2%」' in blocked['2026-11-27'][0]


@pytest.mark.parametrize('sent', [
    '2년 국채 금리는 5거래일 동안 9.0bp 내렸다.',                                # 2회 재현
    '닛케이는 평소의 2배 움직였다.',                                              # 1회 재현
    '닛케이는 5거래일 동안 4% 올랐다.',
    '전력·가스는 최근 5거래일간 시장 수익률보다 0.23%포인트 뒤처졌다.',          # 4회 재현
    '전력·가스는 시장보다 0.23%P 뒤처졌다.',
    '2년 금리는 5거래일 동안 9.0베이시스포인트 내렸다.',
    '<span data-ref="jgb.2Y.value">1.761%에서 9.0bp 내렸다</span>',
    '닛케이는 최근 5거래일 동안 <span data-ref="call_rate.value">1.23</span>% 내렸다.',   # 5회 재현
])
def test_b_figures_written_by_the_writer_are_blocked(sent):
    html, d, news, tg = _b_post('2026-11-27')
    base = _check(html, d, news, tg)
    assert [x for x in _check(_ins_equity(html, sent), d, news, tg) if x not in base]


@pytest.mark.parametrize('sent', [
    '덴소는 0.23% 올랐다.',                                                      # 그날 등락률
    '10년은 <span data-ref="jgb.10Y.chg_bp">-0.4</span>bp 움직였다.',
    '콜금리는 11월 25일 기준 <span data-ref="call_rate.value">1.227</span>%다.',
])
def test_normal_figures_still_pass(sent):
    html, d, news, tg = _b_post('2026-11-27')
    if 'chg_bp' in sent:
        sent = sent.replace('-0.4', f'{d["jgb"]["10Y"]["chg_bp"]}')
    base = _check(html, d, news, tg)
    assert [x for x in _check(_ins_equity(html, sent), d, news, tg) if x not in base] == []


def test_same_sentence_passes_without_b():
    html, snap, news, tg = _load('2026-11-27')
    assert _check(_ins_equity(html, '2년 국채 금리는 5거래일 동안 9.0bp 내렸다.'), snap, news, tg) == []


def test_change_pct_bound_with_bp_and_cited_article_unit_are_blocked():
    html, d, news, tg = _b_post('2026-11-25')
    base = _check(html, d, news, tg)
    sent = '2년 국채 금리는 5거래일 동안 <span data-ref="movers.groups.0.members.0.change_pct">14.2bp</span> 내렸다.'
    assert [x for x in _check(_ins_equity(html, sent), d, news, tg) if x not in base]
    html, d, news, tg = _b_post('2026-11-26')
    base = _check(html, d, news, tg)
    it = next(i for i in news['items'] if str(i['guid']).startswith('e23d7e'))
    m = re.search(r'<p\b[^>]*\bdata-mover\b[^>]*>', html)
    tag = re.sub(r'\sdata-cite="[^"]*"', '', m.group(0))[:-1] + f' data-cite="{it["guid"]}">'
    h2 = html[:m.start()] + tag + '5년 국채 금리는 5거래일 동안 20.0bp 내렸다. ' + html[m.end():]
    assert [x for x in _check(h2, d, news, tg) if x not in base]
