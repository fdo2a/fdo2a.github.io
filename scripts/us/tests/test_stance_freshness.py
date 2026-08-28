from eval_stance_triggers import fresh_metrics


def _file(**kw):
    base = {'report_date': '2026-08-28', 'as_of': '2026-08-28', 'metrics': {'vix_close': 15.2}}
    base.update(kw)
    return base


def test_metrics_from_todays_session_are_kept():
    assert fresh_metrics(_file(), '2026-08-28') == {'vix_close': 15.2}


def test_metrics_keyed_to_another_session_are_dropped():
    assert fresh_metrics(_file(report_date='2026-08-27'), '2026-08-28') == {}


def test_metrics_built_from_a_history_that_stopped_short_are_dropped():
    assert fresh_metrics(_file(as_of='2026-08-27'), '2026-08-28') == {}


def test_metrics_that_cannot_prove_their_freshness_are_dropped():
    # A failed history download leaves as_of null. Unproven is not the same as fresh:
    # letting it through judges today's triggers on whatever partial prices survived.
    assert fresh_metrics(_file(as_of=None), '2026-08-28') == {}


def test_an_empty_metrics_file_stays_empty():
    assert fresh_metrics({}, '2026-08-28') == {}
