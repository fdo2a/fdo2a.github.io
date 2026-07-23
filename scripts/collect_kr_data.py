#!/usr/bin/env python3
"""한국 저녁 마감 브리프 데이터 수집 엔트리.

Naver(수급·거래대금·업종·테마) + yfinance(지수·섹터 멀티기간·장중)를 모아
kr/data/*에 기록. 완성도·수급 신선도 게이트 포함. Do NOT use pykrx/키움 (spec §2).
"""
import argparse
import json
import os
from datetime import datetime, timezone, timedelta

import yfinance as yf

from kr import sources, flows, sectors, program, technical
from kr.themes import rank_themes
from kr.etf_normalize import normalize_top_value
from kr.leadership import flag_leadership

KST = timezone(timedelta(hours=9))
CORE_KEYS = ("indices", "flows", "top_value", "sectors", "themes")
# 기술적 분석 대상(일봉 차트와 동일 4종)
TECH_SPECS = [("코스피", "^KS11"), ("코스닥", "^KQ11"),
              ("SK하이닉스", "000660.KS"), ("삼성전자", "005930.KS")]


def completeness(bundle: dict):
    missing = [k for k in CORE_KEYS if not bundle.get(k)]
    return (len(missing) == 0, missing)


def _report_date():
    df = yf.download("^KS11", period="7d", progress=False, auto_adjust=False)
    if len(df):
        return df.index[-1].date().isoformat()
    return datetime.now(KST).date().isoformat()


def main(outdir: str):
    os.makedirs(outdir, exist_ok=True)
    report_date = _report_date()
    bizdate = report_date.replace("-", "")

    # 지수 — Naver 네이티브(수급과 일치, 마감 후 공식 종가)
    indices = {}
    for name, code in (("KOSPI", "KOSPI"), ("KOSDAQ", "KOSDAQ")):
        try:
            indices[name] = sources.fetch_index(code)
        except Exception:
            pass

    # 수급 (신선도) — 코스피·코스닥
    flows_out = {}
    for mkt, sosok in (("KOSPI", "01"), ("KOSDAQ", "02")):
        try:
            parsed = flows.parse_market_flows(sources.fetch_market_flows(sosok, bizdate))
            fresh = flows.flows_freshness(parsed["latest_date"], report_date,
                                          provisional=(parsed["latest_date"] == report_date))
            flows_out[mkt] = {**parsed, **fresh}
        except Exception as e:
            flows_out[mkt] = {"rows": [], "latest_date": None, "error": str(e)[:120]}
    flows_ok = any(v.get("latest_date") for v in flows_out.values())

    # 프로그램 매매 (차익·비차익·전체 순매수, 억원) — 비-코어, 신선도는 flows와 동일 판정
    program_out = {}
    for mkt, sosok in (("KOSPI", "01"), ("KOSDAQ", "02")):
        try:
            parsed = program.parse_program_flows(sources.fetch_program_flows(sosok, bizdate))
            fresh = flows.flows_freshness(parsed["latest_date"], report_date,
                                          provisional=(parsed["latest_date"] == report_date))
            program_out[mkt] = {**parsed, **fresh}
        except Exception as e:
            program_out[mkt] = {"rows": [], "latest_date": None, "error": str(e)[:120]}

    # 기술적 지표 (이평 20/60/120·볼린저 20±2σ·일목 9/26/52) — 4종, 비-코어
    technical_out = {}
    for name, tk in TECH_SPECS:
        try:
            tdf = yf.download(tk, period="2y", progress=False, auto_adjust=False)
            if hasattr(tdf.columns, "nlevels") and tdf.columns.nlevels > 1:
                tdf.columns = tdf.columns.get_level_values(0)
            if len(tdf):
                technical_out[name] = technical.compute_technical(tdf)
        except Exception as e:
            technical_out[name] = {"error": str(e)[:120]}

    # 거래대금 상위 (ETF 정규화) — 단위 백만원
    try:
        top_value = normalize_top_value(sources.fetch_top_value("0"), top_n=10)
    except Exception:
        top_value = []

    # 섹터 멀티기간 수익률 (대표 ETF, yfinance) — 바 차트용
    sector_rows = []
    try:
        pairs = list(sectors.SECTOR_ETFS.items())
        batch = yf.download([tk for _, tk in pairs], period="2y",
                            progress=False, auto_adjust=False)["Close"]
        for name, tk in pairs:
            if tk not in getattr(batch, "columns", []):
                continue
            sector_rows.append({"name": name, "ret": sectors.multi_horizon_returns(batch[tk])})
    except Exception:
        sector_rows = []
    sector_html = sectors.render_sector_html(sector_rows) if sector_rows else ""

    # 업종 1D 주도 크로스체크 (등락률 ∧ breadth) — Naver 업종 유니버스
    industry = []
    try:
        industry = flag_leadership(sources.fetch_industry(),
                                   ret_key="change_pct", value_key="breadth",
                                   strong_note="폭넓은 상승 주도", weak_note="좁은 상승·개별종목")
    except Exception:
        industry = []

    # 테마 랭킹
    try:
        theme_rows = rank_themes(sources.fetch_themes(7), top=15)
    except Exception:
        theme_rows = []

    # 장중 30분봉 (Naver 분봉 다운샘플) + 당일 OHLC
    intraday = {}
    try:
        intraday["KOSPI"] = sources.fetch_intraday("KOSPI")
        intraday["KOSPI_ohlc"] = sources.fetch_index_ohlc("KOSPI")
    except Exception:
        intraday = {}

    # 일봉 차트 (코스피·코스닥·SK하이닉스·삼성전자) → kr_charts.png
    try:
        import base64 as _b64
        from kr import charts as _charts
        uri = _charts.render_daily_charts(TECH_SPECS)
        with open(os.path.join(outdir, "kr_charts.png"), "wb") as f:
            f.write(_b64.b64decode(uri.split(",", 1)[1]))
    except Exception:
        pass

    bundle = {"report_date": report_date, "indices": indices,
              "flows": flows_out if flows_ok else None,
              "top_value": top_value, "sectors": sector_rows, "themes": theme_rows}
    ok, missing = completeness(bundle)

    # 경제지표: ECOS 키 미발급 → 스텁 (§10)
    econ = {"pending": True, "note": "ECOS API 키 발급 후 구현"}
    if "econ" not in missing:
        missing.append("econ")

    market = {"report_date": report_date, "complete": ok, "missing": missing,
              "indices": indices,
              "flows_date": {m: v.get("flows_date") for m, v in flows_out.items()},
              "flows_provisional": {m: v.get("flows_provisional") for m, v in flows_out.items()}}

    _write(outdir, "kr_market_data.json", market)
    _write(outdir, "kr_flows.json", flows_out)
    _write(outdir, "kr_program.json", program_out)
    _write(outdir, "kr_technical.json", technical_out)
    _write(outdir, "kr_top_value.json", top_value)
    _write(outdir, "kr_industry.json", industry)
    _write(outdir, "kr_theme.json", theme_rows)
    _write(outdir, "kr_intraday.json", intraday)
    _write(outdir, "kr_econ.json", econ)
    with open(os.path.join(outdir, "kr_sector.html"), "w", encoding="utf-8") as f:
        f.write(sector_html)

    print(f"report_date={report_date} complete={ok} missing={missing} "
          f"flows_date={market['flows_date']}")


def _write(outdir, name, obj):
    with open(os.path.join(outdir, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="kr/data")
    args = ap.parse_args()
    main(args.outdir)
