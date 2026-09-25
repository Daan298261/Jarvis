from backend.app.integrations.crucix.client import CrucixClient, CrucixError, normalize


def test_normalize_bounds_and_provenance():
    rows=normalize({"meta":{"sourcesOk":1},"news":[{"title":"Example","url":"https://example.test/a","timestamp":"2026-09-24T06:00:00Z"}]})
    assert len(rows)==1
    assert rows[0]["source"]=="news"
    assert rows[0]["verified"] is True
    assert rows[0]["dedup_key"]


def test_rejects_non_loopback_endpoint():
    try:
        CrucixClient("http://192.168.1.10:3117")
    except CrucixError:
        pass
    else:
        raise AssertionError("non-loopback Crucix endpoint accepted")
