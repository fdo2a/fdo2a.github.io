"""fetch_news.get — Yahoo 종목 피드가 urllib 을 429 로 막을 때 브라우저 지문으로 넘어가는가.

2026-09-22·23 수집에서 MLCC 종목 피드 넷이 재시도까지 전부 429 였다. 로컬에서도 첫
요청부터 429 라 속도 제한이 아니라 TLS 지문 차단이다(curl_cffi 로는 200).
"""
import io
import os
import sys
import urllib.error

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import fetch_news as FN  # noqa: E402


def _refuse(code):
    def urlopen(req, timeout=None, context=None):
        raise urllib.error.HTTPError(req.full_url, code, 'no', {}, io.BytesIO(b''))
    return urlopen


@pytest.fixture
def no_sleep(monkeypatch):
    waits = []
    monkeypatch.setattr(FN.time, 'sleep', waits.append)
    return waits


@pytest.mark.parametrize('code', [429, 403])
def test_a_refused_feed_is_fetched_with_a_browser_fingerprint(monkeypatch, no_sleep, code):
    monkeypatch.setattr(FN.urllib.request, 'urlopen', _refuse(code))
    assert FN.get('https://feeds.finance.yahoo.com/x', None,
                  impersonated=lambda u: '<rss/>') == '<rss/>'
    assert no_sleep == []                      # 우회가 되면 15초씩 기다리지 않는다


def test_when_both_fail_the_429_still_retries_then_raises(monkeypatch, no_sleep):
    monkeypatch.setattr(FN.urllib.request, 'urlopen', _refuse(429))
    tried = []
    with pytest.raises(urllib.error.HTTPError):
        FN.get('https://x', None, retries=2, impersonated=lambda u: tried.append(u))
    assert len(tried) == 3 and no_sleep == [FN.RETRY_WAIT] * 2


def test_a_404_is_not_worth_impersonating(monkeypatch, no_sleep):
    monkeypatch.setattr(FN.urllib.request, 'urlopen', _refuse(404))
    tried = []
    with pytest.raises(urllib.error.HTTPError):
        FN.get('https://x', None, impersonated=lambda u: tried.append(u))
    assert tried == []
