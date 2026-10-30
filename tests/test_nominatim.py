import io
import json
import urllib.error

import pytest

from core import nominatim


class FakeOpen:
    def __init__(self, body=b"[]", error=None):
        self.body = body
        self.error = error
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        if self.error:
            raise self.error
        return io.BytesIO(self.body)


@pytest.fixture(autouse=True)
def fresh_client(monkeypatch):
    nominatim._cache.clear()
    monkeypatch.setattr(nominatim, "_last_call", 0.0)
    sleeps = []
    monkeypatch.setattr(nominatim.time, "sleep", sleeps.append)
    yield sleeps
    nominatim._cache.clear()


def use(monkeypatch, fake):
    monkeypatch.setattr(nominatim.urllib.request, "urlopen", fake)
    return fake


def test_search_sends_query_limited_to_kenya_with_user_agent_and_timeout(monkeypatch):
    fake = use(monkeypatch, FakeOpen(json.dumps([{"osm_id": 1}]).encode()))

    results = nominatim.search("Nakuru", 3)

    assert results == [{"osm_id": 1}]
    request, timeout = fake.requests[0]
    assert "q=Nakuru" in request.full_url
    assert "countrycodes=ke" in request.full_url
    assert "format=jsonv2" in request.full_url
    assert "addressdetails=1" in request.full_url
    assert "limit=3" in request.full_url
    assert request.get_header("User-agent") == nominatim.USER_AGENT
    assert timeout == nominatim.TIMEOUT_SECONDS


def test_repeated_search_ignoring_case_is_served_from_cache(monkeypatch):
    fake = use(monkeypatch, FakeOpen())

    nominatim.search("Nakuru")
    nominatim.search("nakuru")

    assert len(fake.requests) == 1


def test_same_query_with_different_limit_calls_openstreetmap_again(monkeypatch):
    fake = use(monkeypatch, FakeOpen())

    nominatim.search("Nakuru", 5)
    nominatim.search("Nakuru", 1)

    assert len(fake.requests) == 2


def test_cached_search_expires_after_cache_time(monkeypatch):
    fake = use(monkeypatch, FakeOpen())
    monkeypatch.setattr(nominatim, "CACHE_SECONDS", 0)

    nominatim.search("Nakuru")
    nominatim.search("Nakuru")

    assert len(fake.requests) == 2


def test_cache_drops_oldest_search_when_full(monkeypatch):
    use(monkeypatch, FakeOpen())
    monkeypatch.setattr(nominatim, "CACHE_SIZE", 2)

    nominatim.search("Nakuru")
    nominatim.search("Kisumu")
    nominatim.search("Mombasa")

    assert list(nominatim._cache) == ["kisumu|5", "mombasa|5"]


def test_search_waits_between_calls_to_respect_rate_limit(monkeypatch, fresh_client):
    use(monkeypatch, FakeOpen())

    nominatim.search("Nakuru")
    nominatim.search("Kisumu")

    assert len(fresh_client) == 1
    assert 0 < fresh_client[0] <= nominatim.MIN_INTERVAL_SECONDS


def test_network_failure_raises_nominatim_error(monkeypatch):
    use(monkeypatch, FakeOpen(error=urllib.error.URLError("down")))

    with pytest.raises(nominatim.NominatimError):
        nominatim.search("Nakuru")


def test_non_json_answer_raises_nominatim_error(monkeypatch):
    use(monkeypatch, FakeOpen(b"not json"))

    with pytest.raises(nominatim.NominatimError):
        nominatim.search("Nakuru")


def test_answer_that_is_not_a_list_raises_nominatim_error(monkeypatch):
    use(monkeypatch, FakeOpen(b'{"error": "bad"}'))

    with pytest.raises(nominatim.NominatimError):
        nominatim.search("Nakuru")


def test_failed_search_is_not_cached(monkeypatch):
    use(monkeypatch, FakeOpen(error=urllib.error.URLError("down")))
    with pytest.raises(nominatim.NominatimError):
        nominatim.search("Nakuru")

    fake = use(monkeypatch, FakeOpen())
    nominatim.search("Nakuru")

    assert len(fake.requests) == 1
