#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KR 시장 데이터 소스 도달성/차단 테스트 — 로컬(한국 IP)·Actions(미국 IP) 양쪽 동일 실행.
목적: '해외/클라우드 IP에서 각 소스가 막히는가'만 판정. 데이터 신선도가 아니라 reachability 판정이므로
날짜는 확실히 존재하는 과거 구간(2024-06)으로 고정한다."""
import json, sys, traceback
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
HDRS = {"User-Agent": UA, "Accept": "*/*", "Referer": "https://finance.naver.com/"}
FROM, TO = "20240603", "20240607"   # 확실히 존재하는 과거 KRX 영업일 구간

def line(tag, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {tag}: {detail}")

def public_ip():
    try:
        r = requests.get("https://ipinfo.io/json", timeout=10, headers={"User-Agent": UA})
        d = r.json()
        print(f"\n>>> RUNNER IP: {d.get('ip')} / {d.get('country')} / {d.get('org')}\n")
    except Exception as e:
        print(f">>> RUNNER IP: unknown ({e})\n")

def t_yf():
    try:
        import yfinance as yf
        df = yf.download("005930.KS", period="5d", progress=False, auto_adjust=False)
        ok = df is not None and len(df) > 0
        line("yfinance 삼성전자(005930.KS)", ok, f"{len(df) if ok else 0} rows")
        idx = yf.download("^KS11", period="5d", progress=False, auto_adjust=False)
        line("yfinance KOSPI(^KS11)", len(idx) > 0, f"{len(idx)} rows")
    except Exception as e:
        line("yfinance", False, repr(e)[:180])

def t_pykrx():
    try:
        from pykrx import stock
    except Exception as e:
        line("pykrx import", False, f"NOT INSTALLED ({repr(e)[:80]})")
        return
    # (a) 종목 OHLCV
    try:
        df = stock.get_market_ohlcv_by_date(FROM, TO, "005930")
        line("pykrx OHLCV 삼성전자", len(df) > 0, f"{len(df)} rows")
    except Exception as e:
        line("pykrx OHLCV", False, repr(e)[:180])
    # (b) 지수 OHLCV (1001=KOSPI)
    try:
        df = stock.get_index_ohlcv_by_date(FROM, TO, "1001")
        line("pykrx 지수 KOSPI(1001)", len(df) > 0, f"{len(df)} rows")
    except Exception as e:
        line("pykrx 지수", False, repr(e)[:180])
    # (c) 수급: 투자자별 거래대금 (핵심)
    try:
        df = stock.get_market_trading_value_by_investor(FROM, TO, "KOSPI")
        line("pykrx 수급(투자자별 거래대금)", len(df) > 0, f"{len(df)} rows / cols={list(df.columns)[:4]}")
    except Exception as e:
        line("pykrx 수급", False, repr(e)[:180])
    # (d) 업종/섹터 티커 리스트
    try:
        tickers = stock.get_index_ticker_list(date="20240607", market="KOSPI")
        line("pykrx 업종지수 리스트", len(tickers) > 0, f"{len(tickers)} indices")
    except Exception as e:
        line("pykrx 업종리스트", False, repr(e)[:180])

def t_naver():
    # JSON 엔드포인트 (모바일 API)
    json_tests = [
        ("Naver 지수 통합(KOSPI)", "https://m.stock.naver.com/api/index/KOSPI/integration", ["totalInfos"]),
        ("Naver 지수 일별시세(KOSPI)", "https://m.stock.naver.com/api/index/KOSPI/price?pageSize=5&page=1", []),
        ("Naver 종목 통합(삼성전자)", "https://m.stock.naver.com/api/stock/005930/integration", ["totalInfos"]),
        ("Naver 업종/섹터 리스트", "https://m.stock.naver.com/api/stocks/industry?menu=industry", []),
    ]
    for tag, url, wantkeys in json_tests:
        try:
            r = requests.get(url, headers=HDRS, timeout=12)
            ok = r.status_code == 200
            detail = f"HTTP {r.status_code}, {len(r.text)} bytes"
            if ok:
                try:
                    j = r.json()
                    detail += f", JSON keys={list(j.keys())[:5] if isinstance(j, dict) else 'list('+str(len(j))+')'}"
                except Exception:
                    ok = False; detail += ", NOT JSON (blocked/geofenced?)"
            line(tag, ok, detail)
        except Exception as e:
            line(tag, False, repr(e)[:180])
    # HTML 엔드포인트 (EUC-KR) — 수급·테마
    html_tests = [
        ("Naver 시장수급 코스피", "https://finance.naver.com/sise/investorDealTrendDay.naver?bizdate=20240607&sosok=01",
         ["외국인", "기관", "개인"]),
        ("Naver 종목수급 삼성전자", "https://finance.naver.com/item/frgn.naver?code=005930",
         ["외국인", "기관"]),
        ("Naver 테마 페이지", "https://finance.naver.com/sise/theme.naver", ["테마"]),
        ("Naver 업종 페이지", "https://finance.naver.com/sise/sise_group.naver?type=upjong", ["업종"]),
    ]
    for tag, url, wants in html_tests:
        try:
            r = requests.get(url, headers=HDRS, timeout=12)
            r.encoding = "euc-kr"
            body = r.text
            hits = [w for w in wants if w in body]
            ok = r.status_code == 200 and len(hits) == len(wants)
            line(tag, ok, f"HTTP {r.status_code}, {len(body)} bytes, hits={hits}")
        except Exception as e:
            line(tag, False, repr(e)[:180])

if __name__ == "__main__":
    print("=" * 60)
    print("KR DATA SOURCE REACHABILITY TEST")
    print("=" * 60)
    public_ip()
    print("--- yfinance (Yahoo) ---");  t_yf()
    print("\n--- pykrx (KRX 직결) ---");  t_pykrx()
    print("\n--- Naver Finance ---");    t_naver()
    print("\n" + "=" * 60 + "\nDONE")
