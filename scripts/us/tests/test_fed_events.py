from us import fed_events as fe

FEED = '''<?xml version="1.0" encoding="utf-8" ?>
<rss version="2.0"><channel>
  <item>
    <title><![CDATA[Barr, Unlocking Opportunities for Workers]]></title>
    <link><![CDATA[https://www.federalreserve.gov/newsevents/speech/barr20260901a.htm]]></link>
    <description><![CDATA[Speech At the Second-Chance Lending Forum, Washington, D.C.]]></description>
    <pubDate><![CDATA[Tue, 1 Sep 2026 13:05:00 GMT]]></pubDate>
  </item>
  <item>
    <title><![CDATA[Warsh, In Our Time]]></title>
    <link><![CDATA[https://www.federalreserve.gov/newsevents/speech/warsh20260828a.htm]]></link>
    <description><![CDATA[Speech At an economic policy symposium sponsored by the Federal Reserve Bank of Kansas City, Jackson Hole, Wyoming]]></description>
    <pubDate><![CDATA[Fri, 28 Aug 2026 14:00:00 GMT]]></pubDate>
  </item>
</channel></rss>'''

PRESS = '''<rss><channel>
  <item><title>Federal Reserve issues FOMC statement</title>
    <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260819a.htm</link>
    <pubDate>Wed, 19 Aug 2026 18:00:00 GMT</pubDate></item>
  <item><title>Minutes of the Board&amp;#39;s discount rate meetings on July 20 and July 29, 2026</title>
    <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260825a.htm</link>
    <pubDate>Tue, 25 Aug 2026 18:00:00 GMT</pubDate></item>
</channel></rss>'''

# 실제 페이지의 서명줄 배치 (2026-09-02 실측을 줄인 것)
CHAIR_PAGE = ('Home Speeches In Our Time Chairman Kevin Warsh At "Financial Innovation," '
              'an economic policy symposium sponsored by the Federal Reserve Bank of '
              'Kansas City, Jackson Hole, Wyoming Share Thank you. It is great to be here.')
VICE_PAGE = ('Home Speeches Navigating Economic Shocks Vice Chair Philip N. Jefferson '
             'At Stanford University, Stanford, California Share Good afternoon.')
GOV_PAGE = ('Home Speeches Monetary Policy at a Crossroads Governor Christopher J. Waller '
            'At the New York Association for Business Economics Share Thank you.')


def test_parse_feed_reads_cdata_and_dates():
    items = fe.parse_feed(FEED)
    assert [i['title'] for i in items] == ['Barr, Unlocking Opportunities for Workers',
                                           'Warsh, In Our Time']
    assert items[1]['published'] == '2026-08-28'


def test_pubdate_is_not_shifted_by_timezone():
    # 21:00 GMT 를 현지시로 옮기면 날짜가 하루 밀린다. 옮기지 않는다.
    assert fe.parse_pubdate('Wed, 19 Aug 2026 21:30:00 GMT') == '2026-08-19'


def test_slug_date_and_name():
    link = 'https://www.federalreserve.gov/newsevents/speech/warsh20260828a.htm'
    assert fe.slug_date(link) == '20260828'
    assert fe.slug_name(link) == 'warsh'
    assert fe.slug_date('https://x/mediacenter/files/FOMCpresconf20260617.pdf') == '20260617'


def test_in_window_keeps_recent_and_drops_future():
    items = fe.parse_feed(FEED)
    assert [i['published'] for i in fe.in_window(items, '2026-08-31', days=4)] == ['2026-08-28']
    assert fe.in_window(items, '2026-08-27') == []          # 아직 안 나온 문서
    assert len(fe.in_window(items, '2026-09-01', days=4)) == 2


def test_press_kind_classifies_and_excludes_discount_rate_minutes():
    assert fe.press_kind('Federal Reserve issues FOMC statement') == 'fomc_statement'
    assert fe.press_kind('Minutes of the Federal Open Market Committee, July 28-29, 2026') \
        == 'fomc_minutes'
    assert fe.press_kind("Minutes of the Board's discount rate meetings on July 20") is None
    assert fe.press_kind('Federal Reserve announces task force leadership') is None
    assert fe.press_kind('Federal Reserve Board and FOMC release economic projections '
                         'from the June 16-17 meeting') == 'fomc_projections'


def test_byline_reads_role_from_the_page_not_the_feed():
    assert fe.byline(CHAIR_PAGE, 'In Our Time') == ('Chairman', 'Kevin Warsh')


def test_vice_chair_is_not_the_chair():
    # 「Vice Chair」가 「Chair」로 읽히면 부의장 연설이 의장 발언으로 실린다.
    role, name = fe.byline(VICE_PAGE, 'Navigating Economic Shocks')
    assert role == 'Vice Chair'
    assert role not in fe.CHAIR_ROLES
    assert fe.speech_kind({'title': 'Jefferson, Navigating Economic Shocks'}, VICE_PAGE) is None


def test_governor_speech_is_skipped():
    assert fe.speech_kind({'title': 'Waller, Monetary Policy at a Crossroads'}, GOV_PAGE) is None


def test_jackson_hole_is_detected_from_the_venue():
    item = fe.parse_feed(FEED)[1]
    assert fe.speech_kind(item, CHAIR_PAGE) == ('jackson_hole', 'Chairman', 'Kevin Warsh')


def test_ordinary_chair_speech_and_testimony():
    page = 'Home Speeches Economic Outlook Chair Jane Doe At The Exchequer Club Share Hello.'
    assert fe.speech_kind({'title': 'Doe, Economic Outlook'}, page) \
        == ('chair_speech', 'Chair', 'Jane Doe')
    assert fe.speech_kind({'title': 'Doe, Semiannual Report'}, page, feed='testimony')[0] \
        == 'chair_testimony'


def test_statement_sources_include_the_delayed_transcript():
    src = fe.statement_sources('20260819',
                               'https://www.federalreserve.gov/newsevents/pressreleases/monetary20260819a.htm')
    roles = [s['role'] for s in src]
    assert roles == ['statement', 'impl_note', 'projections', 'presconf']
    assert src[-1]['url'].endswith('FOMCpresconf20260819.pdf')


def test_event_key_is_stable_and_readable():
    assert fe.event_key('fomc_statement', '20260819') == 'fomc-statement-20260819'


# ── 인용 대조 ────────────────────────────────────────────────────────────────

CORPUS = ('The Committee decided to lower the target range for the federal funds rate '
          'to 4-1/4 to 4-1/2 percent. Inflation remains somewhat elevated. '
          'The Committee is attentive to the risks to both sides of its dual mandate.')


def test_verbatim_quote_passes():
    assert fe.verify_quote('Inflation remains somewhat elevated.', CORPUS) is None


def test_curly_quotes_and_dashes_do_not_fail_a_real_quote():
    q = '“the target range for the federal funds rate to 4‑1/4 to 4‑1/2 percent”'
    assert fe.verify_quote(q, CORPUS) is None


def test_fabricated_quote_is_caught():
    bad = 'The Committee stands ready to cut rates aggressively if the labor market weakens.'
    assert '원문에 없는 조각' in fe.verify_quote(bad, CORPUS)


def test_fragments_too_short_to_check_are_rejected_not_dropped():
    # 전체는 40자를 넘지만 조각이 전부 25자 미만이면 예전에는 검증 대상이 0개가 됐다.
    q = 'Rates will fall now. [...] Inflation is defeated. [...] Jobs will stay strong.'
    assert '너무 짧은 조각' in fe.verify_quote(q, CORPUS)


def test_hiding_a_negation_behind_an_ellipsis_is_rejected():
    src = 'We do not expect it would be appropriate to reduce our target range this year.'
    q = 'We do [...] expect it would be appropriate to reduce our target range this year.'
    assert '너무 짧은 조각' in fe.verify_quote(q, src)


def test_distant_fragments_cannot_be_stitched():
    src = ('The economy is showing impressive resilience. ' + 'filler sentence here. ' * 200
           + 'We were not scared of them at all in that moment.')
    q = ('The economy is showing impressive resilience. [...] '
         'We were not scared of them at all in that moment.')
    assert '떨어진 조각' in fe.verify_quote(q, src)


def test_reordered_fragments_are_rejected():
    q = ('The Committee is attentive to the risks to both sides [...] '
         'The Committee decided to lower the target range for the federal funds rate')
    assert '순서를 뒤집었다' in fe.verify_quote(q, CORPUS)


def test_too_many_elisions():
    q = ('The Committee decided to lower the target range [...] '
         'Inflation remains somewhat elevated [...] '
         'The Committee is attentive to the risks [...] '
         'to both sides of its dual mandate and will act')
    assert '생략이' in fe.verify_quote(q, CORPUS)


def test_elided_quote_checks_each_side():
    ok = 'The Committee decided to lower the target range [...] Inflation remains somewhat elevated.'
    assert fe.verify_quote(ok, CORPUS) is None
    bad = 'The Committee decided to lower the target range [...] Inflation is falling rapidly now.'
    assert '원문에 없는 조각' in fe.verify_quote(bad, CORPUS)


def test_short_fragments_are_not_used_as_evidence():
    # 25자 미만 조각은 아무 문서에나 들어 있으므로 대조 대상이 아니다.
    assert fe.quote_segments('rates. [...] inflation') == []


def test_source_numbers_allow_the_statements_own_figures():
    nums = fe.source_numbers(CORPUS)
    assert 4.25 in nums and 4.5 in nums      # 「4-1/4 to 4-1/2 percent」의 두 끝
    assert 9.9 not in nums


def test_source_numbers_ignore_figures_without_a_unit():
    # 40,000자 속기록의 전화번호·페이지 번호가 허용 집합에 들어가면 안 된다.
    assert fe.source_numbers('call 202-452-2955 for media inquiries') == set()


def test_source_numbers_understand_the_feds_fractions():
    assert 3.75 in fe.source_numbers('the target range at 3½ to 3¾ percent')


# ── 성명문 변경점 ─────────────────────────────────────────────────────────────

PREV = ('Skip to main content Recent indicators suggest that economic activity has '
        'continued to expand at a solid pace. Inflation remains somewhat elevated. '
        'The Committee decided to maintain the target range at 4-1/2 to 4-3/4 percent. '
        'Voting for the monetary policy action were Kevin Warsh, Chair.')
CURR = ('Skip to main content Recent indicators suggest that economic activity has '
        'moderated in recent months. Inflation remains somewhat elevated. '
        'The Committee decided to lower the target range to 4-1/4 to 4-1/2 percent. '
        'The Committee will assess incoming data. '
        'Voting for the monetary policy action were Kevin Warsh, Chair.')


def test_statement_body_drops_navigation_and_the_vote_roll():
    body = fe.statement_body(PREV)
    assert body.startswith('Recent indicators')
    assert 'Voting for' not in body and 'Skip to main content' not in body


def test_redline_pairs_rewritten_sentences():
    r = fe.redline(PREV, CURR)
    befores = [c['before'] for c in r['changed']]
    afters = [c['after'] for c in r['changed']]
    assert any('continued to expand at a solid pace' in b for b in befores)
    assert any('moderated in recent months' in a for a in afters)
    assert any('maintain the target range' in b for b in befores)
    assert r['added'] == ['The Committee will assess incoming data.']
    assert r['removed'] == []
    assert r['kept'] >= 1


def test_redline_of_an_identical_statement_is_empty():
    r = fe.redline(PREV, PREV)
    assert not r['added'] and not r['removed'] and not r['changed']


def test_statement_body_fails_closed_when_it_cannot_find_the_body():
    # 자를 수 없는 페이지를 그대로 본문으로 삼으면 쿠키 안내가 「변경점」이 된다.
    assert fe.statement_body('Skip to main content Official websites use .gov') is None
    assert fe.redline('Skip to main content', CURR) is None
    assert fe.redline(PREV, 'Skip to main content') is None
