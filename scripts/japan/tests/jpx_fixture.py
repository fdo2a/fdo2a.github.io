"""JPX 지수 파일·네이버 TOPIX 응답의 고정 입력 (일본 일간 v2, 2026-11-19).

숫자만 2026-11-19 01:30 KST 실측 응답(`design-drafts/jp-daily-v2/dl/r3/`)에서 옮겼다. 원문 파일은 커밋하지 않는다.
값 = (currentPrice, previousDayComparison, previousDayRatio) — JPX 원문 글자 그대로(쉼표 포함).
"""
import json

KEYS = ('Topix17Food', 'Topix17Energy', 'Topix17BuildingMaterial', 'Topix17MaterialChemistry', 'Topix17nostrum',
        'Topix17CarTransport', 'Topix17SteelNonferrous', 'Topix17Machine', 'Topix17ElectricalPrecision',
        'Topix17InformationService', 'Topix17ElectricPowerGas', 'Topix17TransportationLogistics',
        'Topix17TradingWholesale', 'Topix17Retail', 'Topix17Bank', 'Topix17Finance', 'Topix17RealEstate')

D1118 = {
    'Topix': ('3,824.00', '-16.02', '-0.42'),
    'Topix17Food': ('487.93', '-1.16', '-0.24'), 'Topix17Energy': ('329.69', '2.14', '0.65'),
    'Topix17BuildingMaterial': ('470.21', '-1.78', '-0.38'), 'Topix17MaterialChemistry': ('387.62', '-2.46', '-0.63'),
    'Topix17nostrum': ('340.06', '-3.36', '-0.98'), 'Topix17CarTransport': ('389.30', '-2.31', '-0.59'),
    'Topix17SteelNonferrous': ('500.09', '-3.61', '-0.72'), 'Topix17Machine': ('788.24', '1.83', '0.23'),
    'Topix17ElectricalPrecision': ('539.97', '5.98', '1.12'), 'Topix17InformationService': ('488.00', '-3.84', '-0.78'),
    'Topix17ElectricPowerGas': ('117.36', '-0.22', '-0.19'),
    'Topix17TransportationLogistics': ('252.49', '-2.94', '-1.15'),
    'Topix17TradingWholesale': ('1,463.15', '-18.69', '-1.26'), 'Topix17Retail': ('439.92', '-6.92', '-1.55'),
    'Topix17Bank': ('436.84', '-5.02', '-1.14'), 'Topix17Finance': ('427.12', '-3.96', '-0.92'),
    'Topix17RealEstate': ('533.56', '-3.28', '-0.61'),
}
D1117 = {
    'Topix': ('3,840.02', '-61.35', '-1.57'),
    'Topix17Food': ('489.09', '0.65', '0.13'), 'Topix17Energy': ('327.55', '-13.33', '-3.91'),
    'Topix17BuildingMaterial': ('471.99', '-10.80', '-2.24'), 'Topix17MaterialChemistry': ('390.08', '-4.10', '-1.04'),
    'Topix17nostrum': ('343.42', '-2.27', '-0.66'), 'Topix17CarTransport': ('391.61', '-2.41', '-0.61'),
    'Topix17SteelNonferrous': ('503.70', '-12.90', '-2.50'), 'Topix17Machine': ('786.41', '-12.62', '-1.58'),
    'Topix17ElectricalPrecision': ('533.99', '-9.36', '-1.72'), 'Topix17InformationService': ('491.84', '0.63', '0.13'),
    'Topix17ElectricPowerGas': ('117.58', '-2.03', '-1.70'),
    'Topix17TransportationLogistics': ('255.43', '-1.54', '-0.60'),
    'Topix17TradingWholesale': ('1,481.84', '-49.21', '-3.21'), 'Topix17Retail': ('446.84', '-1.63', '-0.36'),
    'Topix17Bank': ('441.86', '-15.68', '-3.43'), 'Topix17Finance': ('431.08', '-8.76', '-1.99'),
    'Topix17RealEstate': ('536.84', '-9.50', '-1.74'),
}
D1116 = {
    'Topix': ('3,901.37', '-40.20', '-1.02'),
    'Topix17Food': ('488.44', '3.60', '0.74'), 'Topix17Energy': ('340.88', '-1.77', '-0.52'),
    'Topix17BuildingMaterial': ('482.79', '-6.91', '-1.41'), 'Topix17MaterialChemistry': ('394.18', '-4.45', '-1.12'),
    'Topix17nostrum': ('345.69', '4.03', '1.18'), 'Topix17CarTransport': ('394.02', '-0.33', '-0.08'),
    'Topix17SteelNonferrous': ('516.60', '-25.95', '-4.78'), 'Topix17Machine': ('799.03', '-18.18', '-2.22'),
    'Topix17ElectricalPrecision': ('543.35', '-21.26', '-3.77'), 'Topix17InformationService': ('491.21', '1.47', '0.30'),
    'Topix17ElectricPowerGas': ('119.61', '-0.57', '-0.47'),
    'Topix17TransportationLogistics': ('256.97', '0.90', '0.35'),
    'Topix17TradingWholesale': ('1,531.05', '-11.85', '-0.77'), 'Topix17Retail': ('448.47', '10.75', '2.46'),
    'Topix17Bank': ('457.54', '-3.05', '-0.66'), 'Topix17Finance': ('439.84', '1.39', '0.32'),
    'Topix17RealEstate': ('546.34', '1.97', '0.36'),
}

BASE = 'https://www.jpx.co.jp/market/indices/indices_stock_price3'


def payload(day, drop=(), override=None, raw_extra=''):
    """JPX 값 파일 글자(utf-8-sig). `override` = {키: (cur, cmp, ratio)}."""
    vals = dict(day, **(override or {}))

    def ent(name, v):
        return {'marketName': name, 'currentPrice': v[0], 'previousDayComparison': v[1], 'previousDayRatio': v[2]}
    doc = {'MainStockIndex': {'Topix': ent('TOPIX (東証株価指数)', vals['Topix'])},
           'Topix': {'Topix': ent('TOPIX (東証株価指数)', vals['Topix'])},
           'IndustryTypeStockIndex': {k: ent(k, vals[k]) for k in KEYS if k not in drop}}
    text = json.dumps(doc, ensure_ascii=False)
    if raw_extra:
        text = text[:-1] + raw_extra + '}'
    return '﻿' + text


def http_date(stamp, sec=30, plus_min=0):
    """'202611181659' (JST) → RFC 1123 GMT. +plus_min 분."""
    from datetime import datetime, timedelta, timezone
    t = datetime.strptime(stamp, '%Y%m%d%H%M').replace(tzinfo=timezone(timedelta(hours=9)))
    t = (t + timedelta(seconds=sec, minutes=plus_min)).astimezone(timezone.utc)
    return t.strftime('%a, %d %b %Y %H:%M:%S GMT')


class FakeJPX:
    """슬롯 → {stamp, body, lm, date}. `get(url)` = (status, headers, bytes). `on_call` 로 중간에 슬롯을 밀 수 있다."""

    def __init__(self, slots, missing=('.6',)):
        self.slots = {k: dict(v) for k, v in slots.items()}
        self.calls = []
        self.on_call = None

    def get(self, url):
        self.calls.append(url)
        if self.on_call:
            self.on_call(self, url)
        assert url.startswith(BASE)
        rest = url[len(BASE):]
        is_time = rest.endswith('.time.txt')
        slot = rest[:-len('.time.txt')] if is_time else rest[:-len('.txt')]
        s = self.slots.get(slot)
        if s is None:
            return 404, {}, b'<html>not found</html>'
        if is_time:
            body = s.get('time_body', s['stamp']).encode()
            lm = s.get('time_lm', s.get('lm'))
        else:
            body = s['body'].encode('utf-8')
            lm = s.get('lm')
        h = {'Date': s['date'] if 'date' in s else http_date(s['stamp'], plus_min=120)}
        if lm is not None:
            h['Last-Modified'] = lm
        return s.get('status', 200), h, body


def slot(stamp, day, lm_sec=30, date_plus=130, **kw):
    out = {'stamp': stamp, 'body': payload(day, **{k: v for k, v in kw.items() if k in ('drop', 'override', 'raw_extra')}),
           'lm': http_date(stamp, sec=lm_sec), 'date': http_date(stamp, plus_min=date_plus)}
    out.update({k: v for k, v in kw.items() if k not in ('drop', 'override', 'raw_extra')})
    return out


def standard(target_day=D1118, prev_day=D1117, **over):
    """현재 = 11/18 16:59, .1 = 11/17 16:59, .2 = 11/16 16:59."""
    slots = {'': slot('202611181659', target_day), '.1': slot('202611171659', prev_day),
             '.2': slot('202611161659', D1116), '.3': slot('202611131659', D1116),
             '.4': slot('202611121659', D1116), '.5': slot('202611111659', D1116)}
    slots.update(over)
    return FakeJPX(slots)


NAVER_BASIC = {'closePrice': '3,824.00', 'compareToPreviousClosePrice': '-16.02', 'fluctuationsRatio': '-0.42',
               'localTradedAt': '2026-11-18T15:30:02+09:00', 'marketStatus': 'CLOSE'}
NAVER_DAY = [{'localDate': '20261116', 'closePrice': 3901.37}, {'localDate': '20261117', 'closePrice': 3840.02},
             {'localDate': '20261118', 'closePrice': 3824.0}]


def naver_basic(**over):
    return json.dumps(dict(NAVER_BASIC, **over), ensure_ascii=False)


def naver_day(rows=None):
    return json.dumps(rows if rows is not None else NAVER_DAY)
