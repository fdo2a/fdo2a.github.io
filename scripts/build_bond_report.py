#!/usr/bin/env python3
"""글로벌 채권 EMP 일간 리포트 렌더러.

  python scripts/build_bond_report.py [--datadir bond/data] [--outdir bond/posts]

**산문은 여기서 저작하고 숫자는 전부 데이터 파일에서 렌더한다.** thesis 페이지와 같은
규칙이다 — 손으로 타이핑한 수치는 반드시 흔들린다(과거 FX 방향·유가 등락률 오류 전례).
"""

import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import standing as standing_mod    # noqa: E402
from bond import stance as stance_mod           # noqa: E402
from bond.sources import CREDIT_KO             # noqa: E402

WD = ['월', '화', '수', '목', '금', '토', '일']


# --- 포맷 -------------------------------------------------------------------

def n(v, d=2, dash='—'):
    return dash if v is None else f'{v:,.{d}f}'


def bp(v, dash='—'):
    return dash if v is None else f'{v:+.1f}bp'


def pct(v, d=2, dash='—'):
    return dash if v is None else f'{v:+.{d}f}%'


def cls(v):
    if v is None:
        return ''
    return ' class="up"' if v > 0 else (' class="down"' if v < 0 else '')


def ko_date(iso):
    from datetime import date
    d = date.fromisoformat(iso)
    return f'{d.year}년 {d.month}월 {d.day}일 ({WD[d.weekday()]}요일)'


def esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))



def movers_reading(top, ust):
    """§2 — 그날 상위 mover 의 «구성»을 읽는다. 어느 축이 상위를 차지했는지는 매일 다르다."""
    if not top:
        return '어제 대비 비교할 만한 변화가 없습니다.'
    head = top[:4]
    foreign = [x for x in head if x['kind'] == 'rate' and not x['label'].startswith('US')]
    us_rate = next((x for x in top if x['kind'] == 'rate' and x['label'].startswith('US')), None)
    us_line = ('' if not us_rate else
               f'미국에서 가장 크게 움직인 건 {us_rate["label"].replace("US ", "")} '
               f'{us_rate["value"]:+.1f}bp였고요. ')
    if len(foreign) >= 3:
        return (f'상위 자리를 해외 금리가 채웠습니다. {us_line}'
                f'이런 날 미국 화면만 보고 「별일 없었다」고 적으면 곤란하죠 — '
                f'그날의 사건이 다른 시간대에서 이미 끝나 있었다는 뜻이니까요.')
    if head[0]['kind'] == 'credit':
        return (f'가장 크게 움직인 건 금리가 아니라 크레딧이었습니다. {us_line}'
                f'금리와 스프레드가 따로 논 날은 국채 ETF와 회사채 ETF의 성과가 갈립니다.')
    KIND_KO = {'rate': '금리', 'credit': '크레딧 스프레드', 'fx': '환율',
               'etf': 'ETF 가격', 'vol': '금리 변동성'}
    if head[0]['kind'] == 'rate' and head[0]['label'].startswith('US'):
        return (f'상위는 미국 금리가 차지했습니다. {us_line}'
                f'미국 금리가 움직인 날은 거의 모든 달러 채권이 같이 움직이므로, '
                f'무엇이 그 금리를 밀었는지부터 봅니다.')
    return (f'가장 크게 움직인 건 {KIND_KO.get(head[0]["kind"], head[0]["kind"])} '
            f'쪽이었습니다({head[0]["label"]} {head[0]["value"]:+.1f}{head[0]["unit"]}). '
            f'{us_line}어느 축이 상위를 차지했는지가 그날 무엇을 먼저 봐야 하는지를 말해 줍니다.')


def credit_reading(hy, us_bp):
    chg = hy.get('chg_bp')
    if chg is None:
        return (f'하이일드 스프레드는 {hy["bp"]:,.0f}bp입니다. 오늘은 새 관측이 없어 '
                f'전일 대비 변화를 계산하지 않았습니다.')
    if abs(chg) < 0.05:
        head = f'하이일드 스프레드는 {hy["bp"]:,.0f}bp로 어제와 같습니다.'
    else:
        way = '벌어져' if chg > 0 else '좁아져'
        head = f'하이일드 스프레드는 {chg:+.1f}bp {way} {hy["bp"]:,.0f}bp가 됐습니다.'
    if us_bp is None:
        return head
    if us_bp > 0 and chg < 0:
        tail = ('국채는 손해였지만 회사채는 그 손해를 스프레드로 일부 메운 하루입니다.')
    elif us_bp < 0 and chg > 0:
        tail = ('무위험금리는 내렸는데 신용위험은 커졌습니다 — 국채 ETF는 오르고 '
                '하이일드 ETF는 내릴 수 있는 조합이에요.')
    elif us_bp > 0 and chg > 0:
        tail = '금리도 오르고 스프레드도 벌어졌습니다. 회사채가 양쪽으로 맞은 날입니다.'
    elif us_bp < 0 and chg < 0:
        tail = '금리도 내리고 스프레드도 좁아졌습니다. 채권이 전 구간에서 좋았던 날이에요.'
    elif abs(chg) < 0.5 and abs(us_bp) >= 2:
        move = '오르는' if us_bp > 0 else '내리는'
        tail = (f'금리가 {move} 동안 스프레드는 그대로였습니다. 회사채가 국채와 같은 만큼만 '
                f'움직인 날이라, 오늘 성과 차이는 크레딧이 아니라 듀레이션이 만들었습니다.')
    else:
        tail = '금리도 스프레드도 거의 제자리였습니다.'
    return f'{head} {tail}'


def decomposition_reading(d10):
    if not d10:
        return ('오늘은 명목·실질·기대인플레 세 계열의 기준일이 맞지 않아 분해를 생략했습니다. '
                '날짜가 어긋난 세 다리로 계산하면 항등식이 닫히지 않습니다.')
    drv, n_bp = d10.get('driver_ko'), d10.get('nominal_bp')
    base = (f'왜 굳이 쪼개느냐면 대응이 갈리기 때문이에요. 실질금리가 밀어 올린 상승이면 '
            f'성장과 국채 발행 물량 쪽을 의심하고, 기대인플레가 밀어 올린 상승이면 '
            f'유가·관세·임금 쪽을 봅니다. ')
    if drv == '무변화' or (n_bp is not None and abs(n_bp) < 1):
        tail = (f'{d10.get("date")} 기준으로는 두 축 모두 1bp 안쪽이라 어느 쪽으로도 '
                f'이야기를 만들 만한 날이 아니었죠.')
    elif drv == '실질금리':
        tail = f'{d10.get("date")} 기준 이 움직임은 실질금리가 끌었습니다 — 성장·수급 쪽을 봅니다.'
    elif drv == '기대인플레':
        tail = f'{d10.get("date")} 기준 이 움직임은 기대인플레가 끌었습니다 — 유가·관세·임금을 봅니다.'
    else:
        tail = f'{d10.get("date")} 기준으로는 두 축이 함께 움직였습니다.'
    return (base + tail + f' 수준은 실질 {d10.get("real_level"):.2f}%, '
            f'기대인플레 {d10.get("bei_level"):.2f}%입니다.')


def where(st, short=False, form=None):
    """「지금 어디에 서 있나」를 사람 말로. 문장은 metrics 가 만들어 내려보낸다.

    백분위를 그대로 인쇄하면 읽는 사람이 아무 그림도 못 그린다(2026-09-02 사용자
    지적). 손으로 옮겨 적지 않는다 — 원장이 갱신되면 손타이핑만 뒤처진다.
    `form` 을 주면 종결까지 붙여 준다(받침에 따라 「자리예요」·「뿐이에요」).
    """
    pl = ((st or {}).get('plain')) or {}
    if form:
        return standing_mod.say(pl, form, short)
    return pl.get('short' if short else 'text') or ''


def ccc_reading(hy, ccc):
    hp = (hy.get('standing') or {}).get('percentile')
    cp = (ccc.get('standing') or {}).get('percentile')
    cw, hw = where(ccc.get('standing'), True), where(hy.get('standing'), True)
    # 표본이 짧으면 `plain` 이 아무 말도 안 만든다(30거래일 미만). 그때 이 아래로
    # 내려가면 「CCC 이하는 200bp로 , 지수 전체는 라」 같은 문장이 나온다(codex 2차).
    if hp is None or cp is None or not cw or not hw:
        return ('등급별 분포를 볼 표본이 아직 모자랍니다. 하이일드는 벌어질 때 '
                '아래 등급부터 벌어지므로, 지수 하나만 보지 않는 습관이 필요합니다.')
    if cp - hp >= 30:
        return (f'<b>그런데 여기서 갈립니다.</b> 하이일드 안에서도 가장 등급이 낮은 CCC 이하는 '
                f'{ccc["bp"]:,.0f}bp — {where(ccc.get("standing"), form="formal")}. 지수 전체는 {hw}인데 '
                f'바닥층만 벌어져 있어요. 평균 하나만 보고 「크레딧이 편안하다」고 '
                f'적으면 안 되는 이유가 이 한 줄에 있습니다.')
    if hp - cp >= 30:
        return (f'특이하게도 바닥층이 더 편안합니다. CCC 이하가 {ccc["bp"]:,.0f}bp로 '
                f'{cw}인데 지수 전체는 {hw}입니다. '
                f'질 낮은 쪽으로 돈이 몰린 국면일 수 있어 방향 전환에 특히 약합니다.')
    return (f'등급별로 보면 CCC 이하가 {ccc["bp"]:,.0f}bp로 {cw}, 지수 전체는 {hw}라 '
            f'둘이 같은 방향에 서 있습니다. 층이 갈리지 않은 국면이에요. '
            f'벌어질 때는 아래에서부터 벌어지므로 이 간격을 계속 봅니다.')


def fx_reading(fx):
    rows = [(k, v) for k, v in fx.items() if v.get('change_pct') is not None]
    if not rows:
        return '오늘은 비교할 전일 환율 값이 없어 변화를 계산하지 않았어요.'
    top = max(rows, key=lambda kv: abs(kv[1]['change_pct']))
    if abs(top[1]['change_pct']) < 0.2:
        return '오늘 환율은 이야깃거리가 아니었으니, 대신 환헤지 자체를 짚고 넘어가겠습니다.'
    note = ('' if top[1].get('vs_prev_session', True)
            else f'({top[1].get("vs_date")} 대비) ')
    return (f'{top[0]}가 {note}{top[1]["change_pct"]:+.2f}%로 가장 크게 움직였네요. '
            f'환이 움직인 날은 환노출형과 환헤지형의 성과가 갈리니 헤지 구조부터 확인합니다.')


def etf_reading(etf, ust, tlt, tlt_theory):
    rows = [(t, v.get('change_pct')) for t, v in etf.items()
            if v.get('change_pct') is not None]
    if not rows:
        return '오늘은 ETF 종가 변화를 계산할 전일 값이 없습니다.'
    rows.sort(key=lambda x: x[1])
    low, high = rows[0], rows[-1]
    bp10 = ust['10Y'].get('bp')
    lead = '' if bp10 is None else f'미국 10년물이 {bp10:+.1f}bp 움직인 가운데 '
    low_w = '가장 크게 밀린 건' if low[1] < 0 else '가장 덜 오른 건'
    high_w = '가장 잘 버틴 건' if low[1] < 0 else '가장 많이 오른 건'
    dur, th = tlt.get('duration'), tlt_theory
    tail = ('' if None in (dur, th) else
            f' 듀레이션 {dur:.2f}년짜리 장기 국채 ETF는 30년물 움직임만으로 이론상 '
            f'{th:+.2f}% 정도가 나오는 상품이에요.')
    return (f'{lead}{low_w} {low[0]} {low[1]:+.2f}%, {high_w} {high[0]} '
            f'{high[1]:+.2f}%였습니다.{tail} 듀레이션이 사실상 0인 변동금리 ETF는 금리가 '
            f'어떻게 움직이든 거의 제자리입니다. 같은 「채권 ETF」라도 무엇에 걸려 있는지가 '
            f'이렇게 다릅니다.')


def basket_reading(bm):
    cs = bm.get('contributions') or []
    if not cs:
        return '오늘은 바스켓 기여를 계산할 값이 모자랍니다.'
    top = cs[0]
    heaviest = max(cs, key=lambda c: c['weight'])
    tail = ('' if top['ticker'] == heaviest['ticker'] else
            f' 눈여겨볼 점은 비중이 가장 큰 {heaviest["ticker"]}'
            f'({heaviest["weight_pct"]:.0f}%)가 가장 큰 기여가 아니었다는 겁니다 — '
            f'비중 {top["weight_pct"]:.0f}%짜리 {top["ticker"]}가 더 크게 움직였어요.')
    return (f'바스켓 전체는 {bm["total_pct"]:+.4f}%였습니다. 기여가 가장 컸던 건 '
            f'{top["ticker"]}로 {top["contribution_pct"]:+.4f}%p입니다.{tail} '
            f'비중이 크다고 기여가 큰 게 아니라 <b>비중 × 그날 움직임</b>이 기여이고, '
            f'이 곱셈이 성과 분해의 전부입니다.')


def gap_reading(theory, actual):
    if theory is None or actual is None:
        return '오늘은 둘을 맞대 볼 값이 모자랍니다.'
    gap = abs(actual - theory)
    if gap < 0.05:
        return '거의 맞았습니다.'
    if gap < 0.15:
        return f'{gap:.2f}%포인트 어긋났는데, 이 정도 차이는 늘 생깁니다.'
    return (f'{gap:.2f}%포인트나 어긋났습니다. 이렇게 벌어지는 날은 30년물 하나가 아니라 '
            f'커브 전체가 제각각 움직였다는 뜻이에요.')


# --- 조각 -------------------------------------------------------------------

def shape_sentence(us):
    """커브 형태 문장 — 그날 판정에 따라 갈린다."""
    shape, basis = us.get('shape'), us.get('shape_basis')
    tail = f'({basis} 기준)' if basis else ''
    if not shape:
        return '오늘은 커브 형태를 판정할 만큼 신선한 다리가 모이지 않았습니다.'
    if '평행' in shape:
        return (f'커브 모양은 「{shape}」입니다{tail}. 짧은 쪽과 긴 쪽이 같은 폭으로 움직여 '
                f'기울기가 그대로예요. 이런 날을 스티프닝이나 플래트닝이라 부르면 안 됩니다 — '
                f'커브가 기운 게 아니라 커브 전체가 위아래로 밀린 것이고, 듀레이션이 긴 자산일수록 '
                f'타격이 크다는 점만 달라집니다.')
    if shape == '트위스트':
        return (f'커브는 「트위스트」였습니다{tail} — 짧은 쪽과 긴 쪽이 정확히 같은 폭으로 '
                f'반대로 갔어요. 어느 쪽이 주도했다고 말할 수 없는 모양입니다.')
    if shape == '보합':
        return f'커브는 「{shape}」이었습니다{tail}. 방향을 말할 만한 움직임이 아니었어요.'
    bull, steep = shape.startswith('불'), '스티프' in shape
    who = '짧은 쪽이 더' if steep == bull else '긴 쪽이 더'
    what = '내렸' if bull else '올랐'
    if bull and steep:
        mean = '금리 인하 기대가 앞단에 먼저 반영될 때 나오는 모양입니다'
    elif bull:
        mean = '긴 쪽이 더 사들여진 모양이라 성장 둔화 쪽 이야기와 어울립니다'
    elif steep:
        mean = '긴 쪽이 더 밀린 모양이라 기간프리미엄이나 국채 발행 물량 쪽을 먼저 봅니다'
    else:
        mean = '앞단이 더 밀린 모양이라 정책 기대가 매파적으로 재조정될 때 자주 나옵니다'
    return f'커브 모양은 「{shape}」입니다{tail}. {who} {what}기 때문이고, {mean}.'


def divergence_sentence(div, us_bp):
    """해외 금리를 매일 보는 유일한 정당한 이유 — 동조인가 미국 고유인가."""
    de = (div or {}).get('de')
    if not de:
        return ('해외 금리는 오늘 기준일이 맞는 값이 없어 방향 비교를 하지 않았습니다. '
                '비교가 성립하지 않을 때 억지로 맞대면 하루 어긋난 그림이 나옵니다.')
    head = f'미국 10년물 {de["us_bp"]:+.1f}bp에 독일 10년물은 {de["foreign_bp"]:+.1f}bp였습니다. '
    v = de['verdict']
    if v == '동조':
        body = ('두 시장이 같은 방향으로 비슷하게 움직였으니 글로벌 듀레이션이 함께 팔리거나 '
                '사들여진 날로 읽습니다. 미국 고유 재료를 찾을 게 아니라 전 세계 금리에 같이 '
                '걸린 무언가를 봐야 한다는 뜻이에요.')
    elif v == '미국 고유':
        body = ('미국만 움직였습니다. 이럴 때는 연준·미국 물가·국채 발행 물량·재정처럼 '
                '미국 안쪽 재료를 먼저 의심합니다. 글로벌 금리 이야기로 끌고 가면 원인을 놓칩니다.')
    elif v == '미국 주도':
        body = ('같은 방향이지만 미국이 훨씬 크게 움직였습니다. 글로벌 흐름에 미국 고유 재료가 '
                '얹힌 날로 보고, 연준·물가·국채 발행 쪽을 먼저 확인합니다.')
    elif v.endswith('주도'):
        body = ('같은 방향이지만 유럽 쪽이 훨씬 크게 움직였습니다. 그 지역 재료를 먼저 보되, '
                '우리 상품 구성의 해외 금리 노출이 작다면 방향 확인에서 멈춥니다.')
    elif v.endswith('고유'):
        body = ('미국은 거의 그대로인데 유럽에서만 움직였습니다. 유로존 재료를 보되, '
                '우리 상품 구성의 해외 금리 노출이 작다면 방향만 확인하고 넘어가는 것이 맞습니다.')
    elif v == '반대 방향':
        body = ('두 시장이 서로 다른 쪽으로 움직였어요. 정책 경로가 갈리고 있다는 신호일 수 있어 '
                '국가 간 금리차의 방향을 함께 봅니다.')
    else:
        body = '어느 쪽도 방향을 말할 만큼 움직이지 않았습니다.'
    return head + body


def move_sentence(vol):
    st = (vol or {}).get('standing') or {}
    lvl, chg = (vol or {}).get('move'), (vol or {}).get('move_chg')
    if lvl is None:
        return ''
    # 낡은 값을 오늘 값처럼 인쇄하지 않는다. ^MOVE 는 다른 축보다 늦게 채워지는 날이 있다.
    asof = f'{vol.get("date")} 기준으로 ' if vol.get('stale') else ''
    pos = '' if not where(st) else f' 서 있는 자리는 {where(st, form="and")}.'
    mv = '' if chg is None else f' 전일 대비 {chg:+.2f}'
    tail = ' 오늘 값은 아직 안 채워져 직전 관측을 그대로 적었습니다.' if vol.get('stale') else ''
    return (f'미국채 변동성을 재는 MOVE 지수는 {asof}{lvl:,.2f}{mv}입니다.{pos}{tail} '
            f'채권에서는 주식 변동성 지수보다 이 숫자가 더 중요합니다 — 올라가면 듀레이션 위험과 '
            f'유동성 위험이 같이 커지기 때문이에요.')


def size_word(bp_value):
    if bp_value is None:
        return '판정 불가'
    a = abs(bp_value)
    return '미미' if a < 2 else '보통' if a < 6 else '큼' if a < 12 else '매우 큼'


def headline(m, ust, st10, vol, hy, div):
    """그날 가장 할 말이 있는 것으로 제목을 고른다.

    첫 회차는 제목을 손으로 박았고 다음 거래일에 그대로 거짓이 됐다.
    """
    us_bp = (ust.get('10Y') or {}).get('bp')
    top = (m.get('diff_summary') or {}).get('movers') or []
    lead = top[0] if top else None
    de = (div or {}).get('de') or {}
    pct10 = (st10 or {}).get('percentile')
    if us_bp is not None and abs(us_bp) >= 8:
        if de.get('verdict') == '동조':
            return f'미국 10년물 {us_bp:+.1f}bp, 유럽도 같이 — 글로벌 금리가 함께 움직였습니다'
        if de.get('verdict') == '미국 고유':
            return f'미국 10년물만 {us_bp:+.1f}bp — 원인은 미국 안쪽에 있습니다'
        return f'미국 10년물이 {us_bp:+.1f}bp 움직였습니다'
    if lead and lead['kind'] == 'rate' and lead['abs'] >= 8 and not lead['label'].startswith('US'):
        return f'미국은 조용했고 {lead["label"]}가 {lead["value"]:+.1f}bp 움직였습니다'
    if hy and hy.get('chg_bp') is not None and abs(hy['chg_bp']) >= 10:
        way = '벌어졌' if hy['chg_bp'] > 0 else '좁아졌'
        return f'금리보다 크레딧이 움직였습니다 — 하이일드 스프레드가 {way}습니다'
    if pct10 is not None and pct10 >= 90:
        return '오늘은 조용했지만, 미국 금리가 서 있는 자리는 구간 상단입니다'
    if pct10 is not None and pct10 <= 10:
        return '오늘은 조용했지만, 미국 금리가 서 있는 자리는 구간 하단입니다'
    return '큰 움직임 없이 지나간 하루 — 자리와 대가를 점검합니다'


def forward_sentence(fwd, policy):
    """선도금리 문장 — 값이 없으면 없다고 말한다."""
    f1, f5 = fwd.get('1y1y'), fwd.get('5y5y')
    if f1 is None and f5 is None:
        return ('그런데 오늘은 같은 날짜로 정렬되는 만기가 모자라 선도금리를 뽑지 못했습니다. '
                '이틀치를 섞은 커브에서 뽑은 선도금리는 아무 뜻이 없어서 계산 자체를 건너뜁니다.')
    out = []
    if f1 is not None:
        if policy is None:
            out.append(f'국채 커브에서 뽑은 1년 뒤 1년 금리는 {f1:,.2f}%입니다.')
        else:
            rel = ('지금보다 <b>높습니다</b>' if f1 > policy + 0.05 else
                   '지금보다 <b>낮습니다</b>' if f1 < policy - 0.05 else '지금과 거의 같습니다')
            mean = ('시장이 앞으로 1년 사이 단기금리가 올라가는 쪽에 이미 서 있다는 뜻이죠.'
                    if f1 > policy + 0.05 else
                    '시장이 앞으로 1년 사이 인하를 이미 깔아 놨다는 뜻이에요.'
                    if f1 < policy - 0.05 else
                    '시장이 당분간 정책금리가 그대로일 것으로 본다는 뜻입니다.')
            out.append(f'그런데 국채 커브에서 뽑은 1년 뒤 1년 금리는 {f1:,.2f}%로 {rel}. {mean}')
    if f5 is not None:
        out.append(f'5년 뒤 5년 금리는 {f5:,.2f}%인데, 먼 미래의 중립금리를 시장이 '
                   f'이 언저리로 본다는 얘기가 됩니다.')
    return ' '.join(out)


def carry_gap_sentence(us10, jp10, gap_bp):
    if gap_bp is None or us10 is None or jp10 is None:
        return ('미국채가 일본 국채보다 표면금리가 훨씬 높으니 미국채가 좋다 — '
                '(오늘은 두 나라 관측 날짜가 달라 금리차를 수치로 적지 않습니다) ')
    return (f'미국 10년물이 {us10:,.2f}%고 일본 10년물이 {jp10:,.3f}%니까 '
            f'미국채가 {gap_bp:,.1f}bp 더 준다, 그러니 미국채가 좋다 — ')


def split_sentence(d10, d5):
    """명목 = 실질 + 기대인플레 — 값이 없으면 문장을 만들지 않는다."""
    if not d10 and not d5:
        return ('오늘은 명목·실질·기대인플레 세 계열이 같은 날짜로 모이지 않아 분해를 '
                '생략했습니다. 날짜가 어긋난 세 다리로는 항등식이 닫히지 않습니다.')
    parts = []
    if d10:
        drv = d10.get('driver_ko') or '판정 보류'
        led = ('두 축 모두 거의 안 움직였다는 뜻이에요' if drv == '무변화' else
               '두 축이 함께 끌었다는 뜻이에요' if drv == '동반' else
               f'{drv}가 끌었다는 뜻이에요')
        parts.append(
            f'{d10.get("prev_date")} 대비 {d10.get("date")} 기준 10년물은 명목 '
            f'{d10.get("nominal_bp"):+.1f}bp 가운데 실질이 {d10.get("real_bp"):+.1f}bp, '
            f'기대인플레가 {d10.get("breakeven_bp"):+.1f}bp였습니다. {led}.')
    if d5:
        d5drv = d5.get('driver_ko')
        parts.append(
            f'5년물은 실질 {d5.get("real_bp"):+.1f}bp · 기대인플레 '
            f'{d5.get("breakeven_bp"):+.1f}bp'
            + ('로 역시 큰 변화가 없었고요.' if d5drv == '무변화'
               else f'로 {d5drv} 쪽이었고요.'))
    return ' '.join(parts)


def curve_table(node, title, note='', scope='us'):
    order = ['3M', '6M', '1Y', '2Y', '3Y', '5Y', '7Y', '10Y', '20Y', '30Y', '40Y']
    ten = node.get('tenors') or {}
    rows = []
    for t in order:
        r = ten.get(t)
        if not r:
            continue
        stale = ' <span class="sub">(전일자)</span>' if r.get('stale') else ''
        rows.append(
            f'<tr><td>{t}</td><td>{n(r["level"], 3)}</td>'
            f'<td{cls(r.get("bp"))}>{bp(r.get("bp"))}</td>'
            f'<td class="sub">{r.get("date","")}{stale}</td>'
            f'<td class="sub">{r.get("source","")}</td></tr>')
    if not rows:
        return ''
    return (f'<div class="tbl-scroll"><table data-scope="{scope}"><caption class="sub" '
            f'style="text-align:left;padding:0 0 6px">{title}{note}</caption>'
            '<thead><tr><th>만기</th><th>수익률(%)</th><th>1일</th>'
            '<th>기준일</th><th>출처</th></tr></thead><tbody>'
            + ''.join(rows) + '</tbody></table></div>')


def movers_strip(movers, kinds, limit=6):
    items = [x for x in movers if x['kind'] in kinds][:limit]
    out = []
    for x in items:
        v = x['value']
        c = 'up' if v > 0 else ('down' if v < 0 else '')
        label = CREDIT_KO.get(x['label'], x['label'])
        val = f'{v:+.1f}{x["unit"]}' if x['unit'] != '%' else f'{v:+.2f}%'
        out.append(f'<span class="mt-item"><b>{esc(label)}</b>'
                   f'<span class="{c}" style="font-weight:700">{val}</span></span>')
    return '<div class="mt-strip">' + ''.join(out) + '</div>' if out else ''


def build(datadir, outdir, sitedir):
    mk = json.load(open(os.path.join(datadir, 'bond_market.json')))
    m = json.load(open(os.path.join(datadir, 'bond_metrics.json')))
    ev = json.load(open(os.path.join(datadir, 'bond_stance_eval.json')))
    book = json.load(open(os.path.join(datadir, 'bond_stance.json')))

    rd = m['report_date']
    prev = m['prev_date']
    us = m['curves']['us']
    ust = us['tenors']
    de = m['curves'].get('de') or {}
    det = de.get('tenors') or {}
    jp = m['curves'].get('jp') or {}
    jpt = jp.get('tenors') or {}
    gb = m['curves'].get('gb') or {}
    st10 = m['standing']['us10y']
    st30 = m['standing']['us30y']
    vol = m['vol']
    cr = m['credit']
    hy, ig, ccc = cr['us_hy'], cr['us_ig'], cr['us_hy_ccc']
    fx = m['fx']
    etf = m['etf']
    bm = m['benchmark']
    misc = mk.get('misc') or {}
    ffr = (misc.get('fed_funds') or {}).get('level')
    sofr = (misc.get('sofr') or {}).get('level')
    tp = misc.get('term_premium_10y') or {}
    fwd = us['forwards']

    tlt = etf['TLT']
    tea = m['teaching']
    tlt_theory = tea['tlt_theory_pct']

    head = open(os.path.join(os.path.dirname(datadir), '..', 'bond',
                             '_head.html')).read() if False else HEAD
    lead_line = headline(m, ust, st10, vol, hy, m.get('divergence'))
    us_bp = ust['10Y'].get('bp')
    title = f'{lead_line} | {rd}'
    desc = (f'{ko_date(rd)} 글로벌 채권시장 정리. 미국 10년물 '
            f'{n(ust["10Y"]["level"], 2)}%({bp(us_bp)}), 30년물 '
            f'{n(ust["30Y"]["level"], 2)}%, 하이일드 스프레드 {n(hy["bp"], 0)}bp. '
            f'국채 커브·정책 기대·크레딧·환헤지·채권 ETF를 상품 노출에서 역산한 '
            f'우선순위대로 정리했습니다.')

    P = []
    A = P.append

    # 표본이 짧으면 `plain` 이 None 이라 위치를 말할 수 없다 — 그런 날은 그 절을
    # 통째로 뺀다. 빈 문자열을 문장에 끼워 넣으면 「10년물 4.80%는 , 30년물도」가 된다.
    lead_standing = ''
    if where(st10):
        both = bool(where(st30, short=True))
        lead_standing = (
            f"서 있는 자리는 따로 봅니다. 10년물 {n(ust['10Y']['level'], 2)}%는 "
            + (f"{where(st10, form='clause')}, 30년물 "
               f"{n(ust['30Y']['level'], 2)}%도 "
               f"{where(st30, short=True, form='soft')}. " if both
               else f"{where(st10, form='formal')}. "))

    # ------------------------------------------------------------------ §1
    A(f"""<section id="b-1">
<div class="headline-card">
<h1>{esc(lead_line)}</h1>
<p>{ko_date(rd)} 미국 10년물은 {n(ust['10Y']['level'], 2)}%({bp(us_bp)}), 30년물은
{n(ust['30Y']['level'], 2)}%({bp(ust['30Y'].get('bp'))})로 끝났습니다.
오늘 움직임의 크기는 {size_word(us_bp)} 쪽입니다.</p>
<p>{lead_standing}채권을 사는 쪽에는 표면금리가 그만큼 두툼하다는 뜻이고,
들고 있는 쪽에는 가격 위험이 그만큼 크다는 뜻이기도 합니다.</p>
<p>크레딧은 하이일드 스프레드 {n(hy['bp'], 0)}bp({bp(hy.get('chg_bp'))}),
투자등급 {n(ig['bp'], 0)}bp({bp(ig.get('chg_bp'))})로 마쳤습니다.
{divergence_sentence(m.get('divergence'), us_bp)}</p>
</div>
</section>""")

    # ------------------------------------------------------------------ §2
    top = m['diff_summary']['movers']
    A(f'''<section id="b-2">
<h2>어제 대비 무엇이 바뀌었나</h2>
<div class="card">
<p>채권 운용에서 아침에 가장 먼저 해야 할 일은 값을 읽는 게 아니라 <b>어제와 달라진 것</b>을 찾는 일입니다.
값은 어제도 있었고 오늘도 있지만, 판단을 바꾸는 건 차이니까요. {prev} 대비 크기순으로 줄을 세우면 이렇습니다.</p>
{movers_strip(top, {'rate', 'credit'}, 8)}
<p>{movers_reading(top, ust)}</p>
<p>{credit_reading(hy, ust['10Y'].get('bp'))}</p>
</div>
</section>''')

    # ------------------------------------------------------------------ §3
    # 지면 배분은 노출에서 역산한다(2026-09-01 사용자 지시). 미국 커브는 전 만기 표,
    # 해외는 방향 확인용 압축 표 하나 — 노출이 8%인 축에 표 지면의 절반을 주면 안 된다.
    foreign_rows = []
    for key, label, tenors in (('de', '독일', ('2Y', '10Y', '30Y')),
                               ('jp', '일본', ('10Y', '30Y')),
                               ('gb', '영국', ('10Y',)),
                               ('kr', '한국', ('3Y', '10Y'))):
        node = (m['curves'].get(key) or {}).get('tenors') or {}
        for t in tenors:
            r = node.get(t)
            if not r:
                continue
            stale = ' <span class="sub">(전일자)</span>' if r.get('stale') else ''
            foreign_rows.append(
                f'<tr><td>{label} {t}</td><td>{n(r["level"], 3)}</td>'
                f'<td{cls(r.get("bp"))}>{bp(r.get("bp"))}</td>'
                f'<td class="sub">{r.get("date","")}{stale}</td>'
                f'<td class="sub">{r.get("source","")}</td></tr>')
    foreign_tbl = ('<div class="tbl-scroll"><table data-scope="foreign">'
                   '<caption class="sub" '
                   'style="text-align:left;padding:0 0 6px">해외 국채 — 방향 확인용</caption>'
                   '<thead><tr><th>만기</th><th>수익률(%)</th><th>1일</th>'
                   '<th>기준일</th><th>출처</th></tr></thead><tbody>'
                   + ''.join(foreign_rows) + '</tbody></table></div>')

    # 근거 문장은 두 스프레드 각각의 정렬 여부를 따로 본다. 예전엔 2s10s 만 보고
    # 5s30s 를 무조건 「같은 날짜」라고 불렀고, 다리가 하나 없는 날엔 「기준일이
    # 다릅니다 — None」이 그대로 인쇄될 수 있었다(2026-09-01 codex 지적).
    notes = []
    if us.get('spread_2s10s_bp') is not None and us.get('spread_2s10s_aligned') is False:
        notes.append(f'2년-10년은 기준일이 다릅니다 — {us.get("spread_2s10s_basis")}')
    if us.get('spread_5s30s_bp') is not None and us.get('spread_5s30s_aligned') is False:
        notes.append(f'5년-30년도 기준일이 다릅니다 — {us.get("spread_5s30s_basis")}')
    basis_note = ''
    if notes:
        basis_note = ' 다만 ' + '. '.join(notes) + '.'
        if us.get('spread_5s30s_aligned'):
            basis_note += (f' 같은 날짜끼리 맞댄 5년-30년 '
                           f'{n(us["spread_5s30s_bp"], 1)}bp가 단일 기준일 커브 논의에는 '
                           f'더 맞습니다.')
    fr_pct = (next((r for r in m['exposure']['factors']
                    if r['factor'] == 'foreign_rates'), {}) or {}).get('pct')

    rates_standing = (f"{where(st10, form='clause')}, "
                      if where(st10, form='clause') else '')
    rates_standing_30 = (f"로 {where(st30, short=True, form='formal')}."
                         if where(st30, short=True) else '입니다.')

    A(f"""<section id="b-3">
<h2>국채금리와 커브</h2>
<div class="card">
<p data-standing="rates">미국 10년물은 {n(ust['10Y']['level'], 2)}%입니다. {rates_standing}같은 기간 최저 {n(st10['min'], 2)}%·최고 {n(st10['max'], 2)}% 사이에 있어요. 30년물은
{n(ust['30Y']['level'], 2)}%{rates_standing_30}
오늘 10년물 움직임은 {bp(ust['10Y']['bp'])}로 크기로 치면 {size_word(ust['10Y'].get('bp'))} 쪽입니다.</p>
<p>{move_sentence(vol)}</p>
<p>{shape_sentence(us)}</p>
<p>장단기 금리차는 2년-10년 {n(us['spread_2s10s_bp'], 1)}bp, 5년-30년
{n(us['spread_5s30s_bp'], 1)}bp입니다.{basis_note}</p>
<p>커브가 우상향이라는 건 금리가 하나도 안 움직여도 이익이 난다는 뜻이에요.
시간이 지나면 10년물이던 채권이 9년물이 되고, 커브가 우상향이면 9년 금리가 더 낮으니
그만큼 가격이 오릅니다. 만기가 짧아지며 저절로 붙는 이익이죠.
채권 아이디어를 금리 방향만으로 보면 안 되는 이유가 여기 있습니다.</p>
{curve_table(us, '미국 국채 — 발행값', ' · 5·10·30년은 야후 스팟 지수(주식 종가와 동일자), 나머지 만기는 FRED')}
<h3>해외 금리 — 방향만 확인한다</h3>
<p>이 리포트가 담는 상품 구성에서 해외 금리 노출은 {n(fr_pct, 1)}%입니다(뒤 §8에서 역산합니다).
그래서 분트나 JGB의 커브를 매일 해부하지는 않아요. 대신 <b>딱 하나</b>를 봅니다 —
미국과 같이 움직였나, 아니면 미국만 움직였나.</p>
<p>{divergence_sentence(m.get('divergence'), ust['10Y'].get('bp'))}</p>
{foreign_tbl}
<figure style="margin:16px 0 6px">
<img src="../data/yield_curves.png" alt="주요국 국채 수익률 곡선" style="width:100%;border-radius:12px;border:1px solid #F2F4F6">
<figcaption class="caption" style="margin-top:6px">주요국을 같은 축에 겹쳐 그렸습니다.
세로 간격이 곧 금리차이고, 이 간격이 뒤에 나올 환헤지 이야기의 재료가 됩니다.</figcaption>
</figure>
</div>
</section>""")

    # ------------------------------------------------------------------ §4
    dec = m['decomposition']
    d10 = dec.get('10Y') or {}
    d5 = dec.get('5Y') or {}
    A(f'''<section id="b-4">
<h2>정책 기대와 금리의 원인 분해</h2>
<div class="card">
<p>채권 운용에서 정책금리 자체보다 중요한 건 <b>시장이 이미 무엇을 반영해 놓았는가</b>입니다.
시장이 1년 안에 100bp 인하를 이미 깔아 놨다면 「연준이 내릴 것 같다」는 견해에는 값이 없어요.
값이 있는 견해는 「시장이 반영한 것보다 더 빠르거나 더 느릴 것이다」뿐입니다.</p>
<p>지금 실효 연방기금금리는 {n(ffr,2)}%, 담보부 하루짜리 금리(SOFR)는 {n(sofr,2)}%예요.
{forward_sentence(fwd, ffr)}</p>
<p><b>여기서 조심할 점</b>이 하나 있습니다. 이 선도금리는 정책금리 기대만 담고 있지 않아요.
기간프리미엄(즉 돈을 오래 묶어 두는 데 대해 따로 요구하는 대가)도 함께 들어 있습니다.
뉴욕 연준 추정치로는 10년물의 이 대가가 {n(tp.get('level'),2)}%({tp.get('date','')} 기준)네요.
그러니 선도금리가 높다고 곧바로 인상 기대라고 읽으면 곤란하고, 얼마가 대가이고 얼마가 기대인지를 갈라야 합니다.</p>
<h3>명목 = 실질 + 기대인플레</h3>
<p>{split_sentence(d10, d5)}</p>
<p>{decomposition_reading(d10)}</p>
</div>
</section>''')

    # ------------------------------------------------------------------ §5
    rows = []
    for it in m.get('econ') or []:
        a, p_, u, dv = it['actual'], it['previous'], it['units'], it['diff']
        rows.append(f'<tr><td>{esc(it["name"])}</td><td class="sub">{it["axis"]}</td>'
                    f'<td>{a:,.1f}{u}</td><td>{p_:,.1f}{u}</td>'
                    f'<td{cls(dv)}>{"" if dv is None else f"{dv:+,.1f}"}</td>'
                    f'<td class="sub">{it.get("ref_period","")}</td></tr>')
    econ_tbl = ('<div class="tbl-scroll"><table><thead><tr><th>지표</th><th>축</th>'
                '<th>실제</th><th>직전</th><th>변화</th><th>기준</th></tr></thead><tbody>'
                + ''.join(rows) + '</tbody></table></div>') if rows else ''
    A(f'''<section id="b-5">
<h2>경제지표 — 실제·직전·컨센서스</h2>
<div class="card">
<p>지표를 볼 때 절대 수치만 보면 시장 반응을 못 읽습니다. 물가가 2.5%에서 2.4%로 내려갔어도
컨센서스가 2.2%였다면 채권에는 악재예요. 시장은 숫자가 아니라 <b>예상과의 차이</b>에 반응하니까요.
그래서 순서를 실제 → 컨센서스 → 시장이 이미 반영한 것 → 포지션 → 가격 반응으로 놓고 봅니다.</p>
<p>아래 표는 미국 연준 경제데이터(FRED)에서 결정론적으로 받은 실제·직전 값입니다.
컨센서스는 기관 집계라 여기 없고, 실제 운용에서는 이 표 옆에 컨센서스 열을 붙여 놓고 봅니다.</p>
{econ_tbl}
</div>
</section>''')

    # ------------------------------------------------------------------ §6
    crows = []
    cwins, csess = set(), set()
    for k in ['us_ig', 'us_ig_bbb', 'us_hy', 'us_hy_ccc', 'euro_hy', 'em_sov',
              'em_corp', 'em_hy']:
        v = cr.get(k)
        if not v:
            continue
        s = v.get('standing') or {}
        if s.get('window'):
            cwins.add(s['window'])
            csess.add(s.get('sessions'))
        crows.append(
            f'<tr><td>{CREDIT_KO.get(k,k)}</td><td>{n(v["bp"],0)}bp</td>'
            f'<td{cls(v.get("chg_bp"))}>{bp(v.get("chg_bp"))}</td>'
            f'<td>{where(s, short=True)}</td><td>{s.get("band","")}</td>'
            f'<td class="sub">{v.get("date","")}</td></tr>')
    # 「그만큼 얇다」를 손으로 박아 두면 스프레드가 벌어진 날에도 얇다고 우긴다.
    _hy_side = ((hy.get('standing') or {}).get('plain') or {}).get('side')
    _hy_word = {'low': '그만큼 얇다', 'high': '그만큼 두껍다'}.get(
        _hy_side, '평소와 크게 다르지 않다')
    hy_standing = (f" 숫자만 보면 감이 안 오는데, "
                   f"<b>{where(hy['standing'], form='soft')}</b>."
                   if where(hy['standing']) else '')
    ig_standing = (f"로 {where(ig['standing'], short=True, form='formal')}."
                   if where(ig['standing'], short=True) else '입니다.')

    A(f'''<section id="b-6">
<h2>크레딧 스프레드</h2>
<div class="card">
<p data-standing="credit">미국 하이일드 스프레드는 {n(hy['bp'],0)}bp입니다.{hy_standing}
국채 대신 회사채를 들고 위험을 떠안는 대가가 {_hy_word}는 뜻입니다.
투자등급은 {n(ig['bp'],0)}bp{ig_standing}</p>
<p>{ccc_reading(hy, ccc)}</p>
<p>실무에서 이 갈림이 뜻하는 건 이렇습니다. 지수를 통째로 사는 상품은 좁은 스프레드를 사는 셈이고,
문제가 생기는 곳은 지수 안에서 비중이 작은 바닥층이라 지수 수익률에 잘 안 드러납니다.
그래서 하이일드를 볼 때는 지수 스프레드와 등급별 분포를 같이 보고, 벌어지기 시작하면 아래에서부터 벌어진다는 걸 기억합니다.</p>
<div class="tbl-scroll"><table><thead><tr><th>구간</th><th>OAS</th><th>1일</th>
<th>{('최근 ' + next(iter(cwins)) + ' 안에서') if len(cwins) == 1 and len(csess) == 1 else '표본 안에서'}</th><th>폭</th><th>기준일</th></tr></thead><tbody>{''.join(crows)}</tbody></table></div>
<p class="caption">스프레드는 ICE BofA 지수를 FRED가 게시한 값입니다. 게시가 하루 늦어
주식·ETF 종가일보다 항상 하루 앞선 날짜를 답니다 — 표의 기준일 열이 그 사실을 그대로 보여줍니다.</p>
<p>회사채 수익률을 볼 때는 항상 국채와 스프레드로 쪼개서 봅니다. 예를 들어 오늘 투자등급 회사채 ETF의
만기수익률은 {n(etf['LQD'].get('ytw_pct'),2)}%인데, 같은 듀레이션 언저리의 국채가 {n(ust['7Y']['level'],2)}%(7년물)이니
나머지가 신용위험의 대가입니다. 「몇 퍼센트 준다」로 통째로 보지 않고 「국채 얼마 + 신용위험의 대가 얼마」로 쪼개 읽는 습관이
크레딧 판단의 출발점입니다.</p>
</div>
</section>''')

    # ------------------------------------------------------------------ §7
    us10, jp10, de10 = ust['10Y']['level'], jpt['10Y']['level'], det['10Y']['level']
    A(f'''<section id="b-7">
<h2>환율과 환헤지</h2>
<div class="card">
<p data-standing="fx">달러지수는 {n(fx['DXY']['level'],2)}입니다({fx['DXY'].get('vs_date','—')} 대비 {pct(fx['DXY'].get('change_pct'))}).
유로·달러는 {n(fx['EURUSD']['level'],4)}({pct(fx['EURUSD'].get('change_pct'))}),
달러·엔은 {n(fx['USDJPY']['level'],2)}({pct(fx['USDJPY'].get('change_pct'))})였습니다.
{fx_reading(fx)}</p>
<p>글로벌 채권에서 초보가 가장 많이 놓치는 게 이 부분이에요. {carry_gap_sentence(us10, jp10, m.get('us_jp_10y_bp'))}
이렇게 끝내면 틀립니다. 일본 투자자가 엔으로 자금을 조달해 미국채를 사려면 환위험을 없애야 하고,
그러자면 달러를 선물로 되팔아야 하거든요. 그 비용이 대략 <b>두 나라의 단기금리 차이</b>만큼 붙습니다.</p>
<p>지금 미국 3개월물이 {n(ust['3M']['level'],2)}%예요. 일본의 단기금리는 이보다 훨씬 낮고,
그 차이가 그대로 헤지 비용이 됩니다. 환헤지를 하고 나면 미국채의 표면 수익률 상당 부분이 사라지죠.
남는 게 자국 국채보다 나은지, 그게 실제 판단 기준입니다.</p>
<p>유로 투자자도 사정은 같아요. 독일 10년물 {n(de10,2)}%와 미국 10년물 {n(us10,2)}%의 차이가
{n(m['us_de_10y_bp'],1)}bp인데, 헤지 후에 이 중 얼마가 남느냐가 유럽 자금이 미국채로 오느냐 마느냐를 가릅니다.</p>
<p>이 리포트는 달러 기준으로 쓰기 때문에 아래 표의 수익률은 전부 달러 기준입니다.
다만 원화 투자자라면 여기에 원·달러 변동이 그대로 더해집니다. 오늘 원·달러는
{n(fx['USDKRW']['level'],2)}({pct(fx['USDKRW'].get('change_pct'))})였습니다.</p>
<div class="tbl-scroll"><table><thead><tr><th>통화쌍</th><th>수준</th><th>변화</th><th>비교 대상일</th><th>기준일</th></tr></thead><tbody>
''' + ''.join(
        f'<tr><td>{k}</td><td>{n(v["level"],4)}</td>'
        f'<td{cls(v.get("change_pct"))}>{pct(v.get("change_pct"))}</td>'
        f'<td class="sub">{v.get("vs_date") or "—"}</td>'
        f'<td class="sub">{v.get("date","")}</td></tr>'
        for k, v in fx.items()) + '''</tbody></table></div>
</div>
</section>''')

    # ------------------------------------------------------------------ §8
    erows = []
    for t, v in etf.items():
        erows.append(
            f'<tr><td>{t}</td><td>{n(v.get("close"),2)}</td>'
            f'<td{cls(v.get("change_pct"))}>{pct(v.get("change_pct"))}</td>'
            f'<td>{n(v.get("duration"),2)}</td><td>{n(v.get("ytw_pct"),2)}%</td>'
            f'<td>{n(v.get("oas_bp"),1)}bp</td>'
            f'<td>{n(v.get("aum_bn"), 1)}</td></tr>')
    exp_rows = m['exposure']['factors']
    frows = ''.join(
        f'<tr><td>{r["factor_ko"]}</td><td>{r["pct"]:.1f}%</td>'
        f'<td class="sub">{r["depth"]}</td>'
        f'<td class="sub">{esc(" · ".join(r["watch"]))}</td></tr>' for r in exp_rows)
    seg = m.get('segments') or {}
    erows2 = ''.join(
        f'<tr><td>{row["ticker"]}</td><td class="sub">{row["segment_ko"]}</td>'
        '<td class="sub">'
        + esc(' · '.join(f'{f["factor_ko"]} {f["pct"]:.0f}%' for f in row['factors']))
        + '</td></tr>' for row in (m.get('etf_factors') or []))
    factor_tbl = (
        '<div class="tbl-scroll"><table><caption class="sub" style="text-align:left;'
        'padding:0 0 6px">상품 구성에서 역산한 모니터링 비중</caption><thead><tr>'
        '<th>팩터</th><th>노출</th><th>보는 깊이</th><th>무엇을 보나</th></tr></thead>'
        f'<tbody>{frows}</tbody></table></div>'
        '<div class="tbl-scroll"><table><caption class="sub" style="text-align:left;'
        'padding:0 0 6px">상품별 분해</caption><thead><tr>'
        '<th>종목</th><th>커브 구간</th><th>수익률을 움직이는 것</th></tr></thead>'
        f'<tbody>{erows2}</tbody></table></div>')

    brows = ''.join(
        f'<tr><td>{c["ticker"]}</td><td>{c["weight_pct"]:.0f}%</td>'
        f'<td{cls(c["return_pct"])}>{pct(c["return_pct"])}</td>'
        f'<td{cls(c["contribution_pct"])}>{c["contribution_pct"]:+.4f}%p</td></tr>'
        for c in bm['contributions'])
    A(f'''<section id="b-8">
<h2>ETF — 상품을 고르는 일</h2>
<div class="card">
<p>여러 채권 ETF를 조합해 운용한다면 시장 분석만으로는 모자라요. 이름이 같아도 안이 다르거든요.
같은 미국 투자등급 회사채 ETF라도 듀레이션 {n(etf['LQD'].get('duration'),1)}년짜리와
{n(etf['IGIB'].get('duration'),1)}년짜리는 금리가 움직일 때 완전히 다르게 반응합니다.
그래서 상품 이름이 아니라 <b>듀레이션·만기수익률·스프레드</b>를 보고 골라요.</p>
<p>{etf_reading(etf, ust, tlt, tlt_theory)}</p>
<div class="tbl-scroll"><table><thead><tr><th>종목</th><th>종가</th><th>1일</th>
<th>듀레이션</th><th>만기수익률</th><th>OAS</th><th>순자산(십억$)</th></tr></thead>
<tbody>{''.join(erows)}</tbody></table></div>
<p class="caption">종가는 야후 파이낸스 {rd} 기준이고, 듀레이션·만기수익률·OAS·순자산은
운용사(iShares)가 {etf['AGG'].get('nav_as_of')} 기준으로 공시한 값입니다. 기준일이 하루 다르므로
시장가와 순자산가치의 괴리는 이번 회차에서 계산하지 않았습니다 — 날짜가 어긋난 두 값을 나누면
하루치 시장 움직임이 괴리로 둔갑합니다. 순유입 추정치도 전일 순자산이 쌓인 뒤부터 나옵니다.</p>
<h3>이 상품들이 실제로 무엇에 걸려 있나</h3>
<p>ETF를 고를 때 가장 흔한 실수가 <b>상장 국가로 생각하는 것</b>입니다. 미국 거래소에 상장돼
있어도 안에 담긴 게 독일·일본 국채면 그 나라 금리가 곧 수익률 요인이고, 반대로 이름에
「글로벌」이 붙어 있어도 내용이 미국 국채·미국 회사채면 유럽 금리는 2차 지표예요.
그래서 각 상품을 <b>무엇이 그 수익률을 움직이는가</b>로 쪼갠 다음, 거기서 아침에 무엇을
얼마나 볼지를 역산합니다.</p>
{factor_tbl}
<p>역산 결과는 분명합니다. 미국 금리가 {n(exp_rows[0]['pct'], 1)}%로 압도적이고 해외 금리는
{n((next((r for r in exp_rows if r['factor'] == 'foreign_rates'), {}) or {}).get('pct'), 1)}%뿐이에요.
그러니 분트와 JGB는 방향만 확인하고 넘어가는 것이 맞고, 아침 시간의 대부분은 미국 커브·연준
가격책정·크레딧 스프레드에 써야 합니다. 해외 채권 비중이 늘면 이 표가 먼저 바뀌고
그다음에 보는 시간이 따라 바뀌어야 합니다 — 순서가 반대면 습관이 포트폴리오를 이깁니다.</p>
<p class="caption">팩터 가중치는 각 상품의 듀레이션과 기초자산 구성에서 잡은 근사치입니다.
정확한 민감도는 회귀로 추정해야 하지만, 「무엇을 더 봐야 하는가」를 가르는 데에는 이 해상도로
충분합니다. 커브 구간은 그 상품이 커브의 어디를 타는지를 나타냅니다.</p>

<h3>벤치마크 바스켓을 쪼개 보기</h3>
<p>실제 펀드라면 매일 성과를 요인별로 쪼개서 설명할 수 있어야 합니다. 「오늘 얼마 벌었다」로 끝내지 않고
듀레이션에서 얼마, 크레딧에서 얼마, 환에서 얼마인지를 말할 수 있어야 해요. 아래는 그 연습입니다 —
종합채권 60 · 해외국채 15 · 신흥국채 10 · 하이일드 10 · 물가연동 5로 짠 고정 바스켓의 오늘 하루입니다.</p>
<div class="tbl-scroll"><table><thead><tr><th>종목</th><th>비중</th><th>수익률</th>
<th>기여도</th></tr></thead><tbody>{brows}
<tr><td><b>합계</b></td><td></td><td></td>
<td{cls(bm['total_pct'])}><b>{bm['total_pct']:+.4f}%p</b></td></tr></tbody></table></div>
<p>{basket_reading(bm)}</p>
</div>
</section>''')

    # ------------------------------------------------------------------ §9
    srows = []
    for k in ('duration', 'curve', 'credit'):
        a = ev['assets'][k]
        inc = ' · '.join(f"{t['desc']} (현재 {n(t['actual'],2)})"
                         for t in a['increase'] if t.get('desc'))
        srows.append(
            f'<tr><td><b>{a["name"]}</b></td>'
            f'<td><span data-axis-key="{k}" data-grade="{a["grade"]}">{a["label"]}</span></td>'
            f'<td class="sub">{a["axis"]}</td>'
            f'<td class="sub">{esc(stance_mod.thesis_for(k, m))}</td>'
            f'<td class="sub">{esc(inc)}</td></tr>')
    A(f'''<section id="b-9">
<h2>뷰 3축 — 듀레이션·커브·크레딧</h2>
<div class="card">
<p>이 리포트의 판단은 매일 새로 그리지 않고 <b>전날 것을 물려받습니다</b>. 오늘 값이 어제와 비슷하면
판단도 어제와 같아야 하는데, 매일 백지에서 다시 쓰면 하루 만에 뒤집히기 때문입니다.
그래서 세 축 각각에 미리 조건을 걸어 두고, 그 조건이 실제로 충족됐을 때만 한 칸씩 움직입니다.</p>
<p><b>{rd}은 첫 회차입니다.</b> 세 축 모두 중립에서 출발합니다. 근거 없이 걸린 베팅을 들고 시작하면
조건이 채워질 때까지 그 베팅이 그대로 유지되기 때문에, 시작점은 언제나 「걸지 않음」이어야 합니다.</p>
<div class="tbl-scroll"><table class="stance-tbl"><thead><tr><th>축</th><th>등급</th><th>기준</th>
<th>논거</th><th>무엇이 나와야 움직이나</th></tr></thead><tbody>{''.join(srows)}</tbody></table></div>
<p>규칙은 넷입니다. 하루에 한 축은 한 칸만 움직여요. 중립에서 멀어지는 방향, 즉 베팅을 <b>거는</b>
쪽으로 갈 때만 미리 걸어 둔 조건이 충족돼야 합니다. 줄이는 쪽은 조건 없이 언제든 되고요.
한 번 움직인 뒤에는 3영업일 동안 더 늘리지 못합니다 — 늘리는 데는 인내가 필요하고
줄이는 데는 필요 없다는 원칙이죠.</p>
<p>오늘 세 축의 조건은 전부 충족되지 않았습니다. 10년물은 {n(ust['10Y']['level'],2)}%로
듀레이션을 늘릴 기준선 아래에 있었어요. 2년-10년 금리차도 스티프너 기준과 플래트너 기준
사이 한가운데에 놓였습니다.</p>
<p>크레딧도 마찬가지였습니다. 하이일드 스프레드 {n(hy['bp'],0)}bp는 늘릴 기준선과 줄일 기준선
사이였고요. 그래서 세 축 모두 중립을 유지합니다. 각 기준선의 정확한 값은 위 표의 마지막 칸에 있습니다.</p>
</div>
</section>''')

    # ------------------------------------------------------------------ §10
    A(f'''<section id="b-10">
<h2>오늘의 개념 — 듀레이션</h2>
<div class="card">
<p>채권에서 가장 먼저 몸에 붙여야 하는 숫자가 듀레이션입니다. 정의는 「금리가 1%p 움직일 때
가격이 몇 % 움직이는가」이고, 방향은 반대입니다. 금리가 오르면 가격은 내려요.</p>
<p>오늘이 마침 딱 맞는 예제를 줬습니다. 만기 20년 이상 국채 ETF는 듀레이션이 {n(tlt.get('duration'),2)}년입니다.
오늘 30년물 금리가 {bp(ust['30Y']['bp'])} 움직였으니, 공식대로면 가격은
−{n(tea['tlt_duration'],2)} × {n(ust['30Y']['bp'],1)} ÷ 100 = <b>{pct(tlt_theory)}</b>가 나와야 합니다.
실제로는 {pct(tlt.get('change_pct'))}였어요. 거의 맞았습니다.</p>
<p>완전히 똑같지 않은 이유도 알아 둘 만해요. ETF가 담은 채권은 30년물 하나가 아니라 20년부터 30년까지
섞여 있고, 그 구간의 금리가 저마다 조금씩 다르게 움직였거든요. 게다가 듀레이션은 직선으로 어림한 값이라
금리가 크게 움직일수록 오차가 커집니다. 이 휘어지는 정도를 볼록성이라 부르고, 큰 폭 변동에서는 이것까지 같이 봐요.</p>
<p>실무에서는 이 공식을 이렇게 씁니다. 포트폴리오 듀레이션이 {n(tea['ref_duration'],0)}이면
금리가 {n(tea['ref_bp'],0)}bp 오를 때 대략 {pct(tea['ref_impact_pct'])} 손실이죠.
벤치마크 듀레이션이 {n(tea['benchmark_duration'],1)}인데 우리가 {n(tea['portfolio_duration'],1)}이라면
{n(tea['active_duration'],1)}년만큼 금리 하락에 더 걸어 둔 셈이고, 그만큼이 그날 성과 차이의 대부분을 설명해요.
채권 운용에서 「지금 얼마나 걸려 있나」는 결국 이 한 숫자입니다.</p>
</div>
</section>''')

    body = '\n'.join(P)
    html = (HEAD.replace('{{TITLE}}', esc(title)).replace('{{DESC}}', esc(desc))
            .replace('{{DATE}}', rd).replace('{{KODATE}}', ko_date(rd))
            + body + FOOT.replace('{{DATE}}', rd)
            .replace('{{PREV}}', prev or '—')
            .replace('{{SESSIONS}}', str(m['sessions_in_ledger'])))

    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f'{rd}.html')
    open(out, 'w').write(html)
    print(f'✓ {out}  ({len(html):,} bytes)')
    return out, title, desc, rd


HEAD = '''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{{DESC}}">
<link rel="canonical" href="https://fdo2a.github.io/bond/posts/{{DATE}}.html">
<meta property="og:type" content="article">
<meta property="og:title" content="{{TITLE}}">
<meta property="og:url" content="https://fdo2a.github.io/bond/posts/{{DATE}}.html">
<meta property="og:description" content="{{DESC}}">
<title>{{TITLE}}</title>
<style>
:root { --blue:#0064FF; --ink:#191F28; --sub:#4E5968; --muted:#8B95A1;
  --border:#E5E8EB; --border2:#F2F4F6; --up:#00A85A; --upbg:#E8F8EE;
  --down:#FF4040; --downbg:#FFE8E8; --infobg:#E8F2FF; }
* { box-sizing: border-box; }
body { font-family: 'Toss Product Sans', Pretendard, 'Noto Sans CJK KR', -apple-system, sans-serif;
  letter-spacing: -0.01em; background: #F2F4F6; color: var(--ink); margin: 0;
  word-break: keep-all; overflow-wrap: break-word; }
.container { max-width: 1120px; margin: 0 auto; padding: 0 20px 60px; }
.topbar { background: #fff; border-bottom: 1px solid var(--border2); padding: 14px 20px; }
.topbar-inner { max-width: 1120px; margin: 0 auto; display: flex; align-items: baseline; gap: 10px; }
.brand { color: var(--blue); font-weight: 800; font-size: 15px; }
.topbar-date { color: var(--muted); font-size: 13px; }
.card { background: #fff; border-radius: 14px; border: 1px solid var(--border2);
  padding: 20px 22px; margin: 16px 0; break-inside: avoid-page; }
section { break-inside: avoid-page; margin-bottom: 8px; }
h1 { font-size: 22px; margin: 0 0 10px; line-height: 1.4; }
h2 { font-size: 18.5px; font-weight: 800; margin: 26px 0 12px; padding-left: 12px; position: relative; }
h2::before { content:""; position:absolute; left:0; top:2px; bottom:2px; width:6px;
  border-radius:6px; background: var(--blue); }
h3 { font-size: 16px; font-weight: 800; margin: 22px 0 8px; }
p { font-size: 16px; line-height: 1.78; margin: 0 0 15px; color: var(--ink); max-width: 42em; }
p:last-child { margin-bottom: 0; }
.caption, .sub { font-size: 12.5px; color: var(--muted); }
.sub { font-weight: 600; }
.headline-card { background: var(--infobg); border-radius: 14px; padding: 22px 24px; margin: 16px 0; }
.up { color: var(--up); } .down { color: var(--down); }
table { border-collapse: collapse; width: 100%; font-size: 14.5px; font-variant-numeric: tabular-nums; }
thead th { background: var(--border2); border-bottom: 2px solid var(--blue); font-weight: 800;
  text-align: right; padding: 9px 10px; }
thead th:first-child, td:first-child { text-align: left; }
tbody td { padding: 8px 10px; border-bottom: 1px solid var(--border2); text-align: right; }
.tbl-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 10px; margin: 12px 0 16px; }
.mt-strip { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 16px; }
.mt-item { display: inline-flex; align-items: baseline; gap: 6px; padding: 7px 11px;
  background: #F9FAFB; border: 1px solid #F2F4F6; border-radius: 9999px;
  font-size: 13.5px; white-space: nowrap; }
.mt-item b { font-weight: 700; }
.reading-map { display: flex; align-items: center; gap: 8px; overflow-x: auto;
  margin: -2px 0 20px; padding: 10px 2px 4px; scrollbar-width: none; }
.reading-map::-webkit-scrollbar { display: none; }
.reading-map-label { flex: 0 0 auto; color: #8B95A1; font-size: 12px; font-weight: 700; }
.reading-map a { flex: 0 0 auto; color: #4E5968; background: #fff; border: 1px solid #E5E8EB;
  border-radius: 9999px; padding: 6px 11px; font-size: 12.5px; font-weight: 700;
  line-height: 1.2; text-decoration: none; }
.footer-note { border-top: 1px solid var(--border); margin-top: 30px; padding-top: 16px;
  font-size: 12.5px; color: var(--muted); line-height: 1.7; }
.stance-tbl { table-layout: fixed; }
@media (min-width: 561px) {
  .stance-tbl th:nth-child(1), .stance-tbl td:nth-child(1) { width: 10%; }
  .stance-tbl th:nth-child(2), .stance-tbl td:nth-child(2) { width: 14%; text-align: left; }
  .stance-tbl th:nth-child(3), .stance-tbl td:nth-child(3) { width: 14%; text-align: left; }
  .stance-tbl th:nth-child(4), .stance-tbl td:nth-child(4) { width: 31%; text-align: left; }
  .stance-tbl th:nth-child(5), .stance-tbl td:nth-child(5) { width: 31%; text-align: left; }
}
@media (max-width: 560px) {
  .container { padding-left: 14px; padding-right: 14px; }
  table { font-size: 11px; }
  th, td { padding: 5px 7px; white-space: nowrap; }
  th:first-child, td:first-child { white-space: normal; }
  .card { padding: 16px 16px; }
  .stance-tbl, .stance-tbl tbody, .stance-tbl tr, .stance-tbl td { display: block; width: auto; }
  .stance-tbl thead { display: none; }
  .stance-tbl tr { background:#fff; border:1px solid #E5E8EB; border-radius:12px;
    padding:12px 14px; margin-bottom:10px; }
  .stance-tbl td { padding:0; border:none; text-align:left; white-space:normal; }
}
@media (min-width: 1024px) {
  p, .caption, .sub, li { max-width: none; }
  p:not([class]) { font-size: 17px; line-height: 1.8; }
  h1 { font-size: 25px; } h2 { font-size: 20px; } h3 { font-size: 17px; }
}
</style>
</head>
<body>
<div class="topbar"><div class="topbar-inner">
<span class="brand">Global Bond Desk</span>
<span class="topbar-date">{{KODATE}} 글로벌 채권시장 정리</span>
</div></div>
<div style="max-width:1120px;margin:0 auto;padding:14px 18px 0;display:flex;align-items:center;gap:10px;">
  <a href="../index.html" style="text-decoration:none;background:#fff;border:1px solid #E5E8EB;border-radius:9999px;padding:6px 14px;font-size:12px;font-weight:700;color:#191F28;">‹ 전체 보고서</a>
  <a href="../index.html" style="text-decoration:none;font-size:14px;font-weight:800;color:#0064FF;letter-spacing:-0.02em;">Global Bond Desk</a>
</div>
<div class="container">
'''

FOOT = '''
<div class="footer-note">
기준일 {{DATE}} · 직전 비교일 {{PREV}} · 누적 원장 {{SESSIONS}}거래일<br>
데이터: 미국 연준 경제데이터(FRED) · 독일 분데스방크 · 유럽중앙은행 · 일본 재무성 · 영란은행 · iShares · 야후 파이낸스.
축마다 게시 시차가 달라 각 표에 기준일과 출처를 함께 실었습니다.<br>
내재선도금리는 현물 수익률 곡선을 무이표채로 근사해 계산한 값이고, ETF 순유입은 순자산 변화에서
가격 수익분을 뺀 추정치입니다.<br>
본 자료는 정보 제공과 학습 목적으로 작성된 것으로, 특정 종목의 매수·매도 권유가 아닙니다.
</div>
</div>
</body>
</html>
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='bond/data')
    ap.add_argument('--outdir', default='bond/posts')
    ap.add_argument('--sitedir', default='.')
    a = ap.parse_args()
    build(a.datadir, a.outdir, a.sitedir)


if __name__ == '__main__':
    main()
