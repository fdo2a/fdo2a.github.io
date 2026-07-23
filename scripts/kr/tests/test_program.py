import os

from kr.program import parse_program_flows

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "program_kospi.html")


def _html():
    with open(FIX, encoding="utf-8") as f:
        return f.read()


def test_parse_program_reads_latest_row():
    d = parse_program_flows(_html())
    assert d["latest_date"] == "2026-07-22"
    top = d["rows"][0]
    assert top["arb_net"] == 12
    assert top["narb_net"] == 15243
    assert top["total_net"] == 15255
    assert top["total_buy"] == 108985 and top["total_sell"] == 93730


def test_parse_program_handles_negative_net():
    d = parse_program_flows(_html())
    row = next(r for r in d["rows"] if r["date"] == "2026-07-16")
    assert row["arb_net"] == -2327
    assert row["narb_net"] == -10684
    assert row["total_net"] == -13011


def test_parse_program_row_count_and_date_format():
    d = parse_program_flows(_html())
    assert len(d["rows"]) == 10
    assert all(len(r["date"]) == 10 and r["date"][4] == "-" for r in d["rows"])


def test_parse_program_empty_html():
    d = parse_program_flows("<html><body>no table</body></html>")
    assert d["rows"] == [] and d["latest_date"] is None
