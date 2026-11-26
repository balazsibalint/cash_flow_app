"""A szintetikus próbacsomag (scripts/make_edge_cases.py) a teljes HTTP-folyamaton, mockolt MNB-vel, LLM nélkül."""

import pytest

from scripts.make_edge_cases import build_cases
from tests.test_api import TODAY, env, upload  # noqa: F401  (az `env` fixture)

CASES = build_cases(TODAY)


@pytest.mark.parametrize("case", CASES, ids=[c.filename for c in CASES])
def test_edge_case_gets_expected_outcome(env, case):  # noqa: F811
    r = upload(env, case.data, case.filename)
    if case.http_status is not None:
        assert r.status_code == case.http_status
        assert r.json()["detail"]  # magyar hibaüzenet
        return

    assert r.status_code == 200
    body = r.json()
    inv = body["invoice"]
    assert inv["status"] == case.status, inv["status_reason"]
    assert inv["fx_provisional"] is case.provisional
    codes = [m["code"] for m in inv["messages"]]
    for code in case.warnings:
        assert code in codes
    if case.status == "ok":
        assert isinstance(inv["gross_huf"], int)
    else:
        assert inv["gross_huf"] is None and inv["status_reason"]


def test_whole_pack_leaves_only_ok_invoices_in_report(env):  # noqa: F811
    for case in CASES:
        upload(env, case.data, case.filename)
    report = env.client.get("/api/report").json()
    expected_ok = sum(c.status == "ok" for c in CASES)
    assert report["counts"]["ok"] == expected_ok
    assert report["counts"]["provisional"] == sum(c.provisional for c in CASES)
    assert env.client.get("/api/health").json()["status"] == "ok"
