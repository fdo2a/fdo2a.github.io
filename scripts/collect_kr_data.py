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

from kr import sources, flows, flows_intraday, sectors, program, technical
from kr import econ as kr_econ
from kr.themes import rank_themes
from kr.etf_normalize import normalize_top_value
from kr.leadership import flag_leadership

KST = timezone(timedelta(hours=9))
# themes는 2026-07-29 사용자 지시로 리포트 테마 섹션이 폐지되면서 비-코어로 강등.
# 수집은 계속하되(재도입 대비·업종 크로스체크 참고용) 발행 게이트를 막지 않는다.
CORE_KEYS = ("indices", "flows", "top_value", "sectors")
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

    # 장중 수급 궤적 (누적 순매수 스냅샷 → 30분 앵커·극값·부호 전환) — 비-코어.
    # 확정 수치가 아니다: 정규장 마지막값과 일별 확정치는 정정 때문에 갈린다.
    intraday_flows = {"unit": "억원", "date": report_date,
                      "basis": "장중 누적 순매수 스냅샷 — 확정 일별 수치와 다를 수 있음"}
    for mkt, sosok in (("KOSPI", "01"), ("KOSDAQ", "02")):
        try:
            rows = flows_intraday.collect_pages(
                lambda pg, s=sosok: flows_intraday.parse_intraday_flows(
                    sources.fetch_intraday_flows(s, bizdate, pg)))
            series = flows_intraday.build_series(rows)
            # 일별 수급이 전 거래일 기준이면 장중 궤적도 당일이라 부르지 않는다.
            series["stale"] = bool(flows_out.get(mkt, {}).get("stale"))
            intraday_flows[mkt] = series
        except Exception as e:
            intraday_flows[mkt] = {"points": [], "error": str(e)[:120]}
    intraday_flows_ok = any((intraday_flows.get(m) or {}).get("points")
                            for m in ("KOSPI", "KOSDAQ"))

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

    # 장중 30분봉 (Naver 분봉 다운샘플) + 당일 OHLC — 코스닥은 수급 차트 우축에도 쓴다
    intraday = {}
    for code in ("KOSPI", "KOSDAQ"):
        try:
            intraday[code] = sources.fetch_intraday(code)
            intraday[f"{code}_ohlc"] = sources.fetch_index_ohlc(code)
        except Exception:
            pass

    # 일봉 차트 (코스피·코스닥·SK하이닉스·삼성전자) → kr_charts.png
    try:
        import base64 as _b64
        from kr import charts as _charts
        uri = _charts.render_daily_charts(TECH_SPECS)
        with open(os.path.join(outdir, "kr_charts.png"), "wb") as f:
            f.write(_b64.b64decode(uri.split(",", 1)[1]))
    except Exception:
        pass

    # 장중 수급 차트 (누적 순매수 3선 + 지수 우축) → kr_flows_intraday.png
    try:
        import base64 as _b64
        from kr import charts as _charts
        uri = _charts.render_intraday_flow_chart(intraday_flows, intraday)
        if uri:
            with open(os.path.join(outdir, "kr_flows_intraday.png"), "wb") as f:
                f.write(_b64.b64decode(uri.split(",", 1)[1]))
    except Exception:
        pass

    bundle = {"report_date": report_date, "indices": indices,
              "flows": flows_out if flows_ok else None,
              "top_value": top_value, "sectors": sector_rows, "themes": theme_rows}
    ok, missing = completeness(bundle)

    # 경제지표: ECOS(국고채·기준금리·단기금리). 비-코어 — 실패해도 발행을 막지 않는다.
    econ = kr_econ.collect()
    if econ.get("pending") or econ.get("missing"):
        if "econ" not in missing:
            missing.append("econ")
    if not intraday_flows_ok:
        missing.append("flows_intraday")

    market = {"report_date": report_date, "complete": ok, "missing": missing,
              "indices": indices,
              "flows_date": {m: v.get("flows_date") for m, v in flows_out.items()},
              "flows_provisional": {m: v.get("flows_provisional") for m, v in flows_out.items()}}

    _write(outdir, "kr_market_data.json", market)
    _write(outdir, "kr_flows.json", flows_out)
    _write(outdir, "kr_flows_intraday.json", intraday_flows)
    _write(outdir, "kr_program.json", program_out)
    _write(outdir, "kr_technical.json", technical_out)
    _write(outdir, "kr_top_value.json", top_value)
    _write(outdir, "kr_industry.json", industry)
    _write(outdir, "kr_theme.json", theme_rows)
    _write(outdir, "kr_intraday.json", intraday)
    _write(outdir, "kr_econ.json", econ)
    with open(os.path.join(outdir, "kr_sector.html"), "w", encoding="utf-8") as f:
        f.write(sector_html)

    # 「오늘의 장」 재료. 비-코어 — 실패해도 나머지 산출물은 나간다.
    try:
        from kr import session as kr_session
        md = None
        for cand in ("data/market_data.json", "../data/market_data.json"):
            if os.path.exists(cand):
                with open(cand, encoding="utf-8") as f:
                    md = json.load(f)
                break

        fut = {}
        for _, t in kr_session.FUTURES:
            try:
                h = yf.Ticker(t).history(period="5d", interval="30m")
                if h is not None and len(h):
                    h.index = h.index.tz_convert("America/New_York")
                    fut[t] = [{"t": i.isoformat(), "close": float(r["Close"])}
                              for i, r in h.iterrows()]
            except Exception:
                pass

        peers = {}
        for name, t in kr_session.PEERS:
            try:
                c = yf.Ticker(t).history(period="10d")["Close"].dropna()
                if len(c) >= 2:
                    peers[name] = float(c.iloc[-1] / c.iloc[-2] - 1) * 100
            except Exception:
                pass

        kospi_pct = (indices.get("KOSPI") or {}).get("change_pct")
        _write(outdir, "kr_session.json", {
            "report_date": report_date,
            "us_prev": kr_session.us_prev(md, report_date),
            "us_futures_during_kr": {
                lab: kr_session.kr_hours_window(fut.get(t), report_date)
                for lab, t in kr_session.FUTURES},
            "asia_peers": kr_session.asia_peers(peers, kospi_pct),
        })
        print(f"session: 아시아 {len(peers)}종 / 미국 선물 {len(fut)}종")
    except Exception as e:
        print(f"kr session failed: {e}")

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
