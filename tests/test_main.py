import json
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from main import app, limiter


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset rate limiter state before each test."""
    try:
        limiter.reset()
    except Exception:
        pass
    yield


@pytest.fixture
def client():
    return TestClient(app)


MOCK_PARAMS = {
    "genres": [35],
    "keywords": ["funny"],
    "vote_floor": 6.5,
    "gem_mode": False,
    "sort_by": "popularity.desc",
}

MOCK_MOVIES = [
    {
        "id": i + 1,
        "title": f"Movie {i + 1}",
        "overview": "A movie.",
        "poster_path": "/p.jpg",
        "release_date": "2020-01-01",
        "vote_average": 7.5,
        "vote_count": 500,
        "genre_ids": [35],
        "adult": False,
        "backdrop_path": "/b.jpg",
        "original_language": "en",
        "original_title": f"Movie {i + 1}",
        "popularity": 10.0,
        "video": False,
    }
    for i in range(5)
]

MOCK_DETAIL = {
    "imdb_id": "tt1234567",
    "runtime": 120,
    "tagline": "Great film.",
    "genres": ["Comedy"],
}

MOCK_OMDB = {
    "imdb_rating": "7.5",
    "rt_score": "85%",
    "rated": "PG-13",
}


def _service_mocks():
    """Return context manager stack that mocks all external service calls."""
    return [
        patch("main.interpret_mood", new_callable=AsyncMock, return_value=MOCK_PARAMS),
        patch("main.interpret_group_mood", new_callable=AsyncMock, return_value=MOCK_PARAMS),
        patch("main.discover_movies", new_callable=AsyncMock, return_value=MOCK_MOVIES),
        patch("main.get_movie_detail", new_callable=AsyncMock, return_value=MOCK_DETAIL),
        patch("main.enrich_with_omdb", new_callable=AsyncMock, return_value=MOCK_OMDB),
    ]


class TestHealthCheck:

    def test_root_returns_status(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert r.json() == {"status": "Hugin is watching"}


class TestHealthEndpoint:

    def test_health_returns_omdb_stats(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "omdb" in data
        assert "calls" in data["omdb"]
        assert "limit" in data["omdb"]


class TestPasswordHash:

    def test_returns_hash(self, client):
        r = client.get("/password-hash")
        assert r.status_code == 200
        data = r.json()
        assert "hash" in data
        assert len(data["hash"]) == 16

    def test_hash_is_string(self, client):
        r = client.get("/password-hash")
        assert isinstance(r.json()["hash"], str)


class TestRecommendEndpoint:

    def test_valid_mood_returns_results(self, client):
        mocks = _service_mocks()
        for m in mocks:
            m.start()
        try:
            r = client.post("/recommend", json={"mood": "something funny"})
            assert r.status_code == 200
            data = r.json()
            assert "results" in data
            assert len(data["results"]) > 0
        finally:
            for m in mocks:
                m.stop()

    def test_results_contain_expected_fields(self, client):
        mocks = _service_mocks()
        for m in mocks:
            m.start()
        try:
            r = client.post("/recommend", json={"mood": "something funny"})
            movie = r.json()["results"][0]
            assert "title" in movie
            assert "imdb_id" in movie
            assert "genres" in movie
            assert "vote_average" in movie
        finally:
            for m in mocks:
                m.stop()

    def test_params_used_in_response(self, client):
        mocks = _service_mocks()
        for m in mocks:
            m.start()
        try:
            r = client.post("/recommend", json={"mood": "something funny"})
            data = r.json()
            assert "params_used" in data
            assert data["params_used"]["genres"] == [35]
        finally:
            for m in mocks:
                m.stop()

    def test_empty_mood_returns_422(self, client):
        r = client.post("/recommend", json={"mood": ""})
        assert r.status_code == 422

    def test_mood_too_long_returns_422(self, client):
        r = client.post("/recommend", json={"mood": "a" * 501})
        assert r.status_code == 422

    def test_missing_mood_field_returns_422(self, client):
        r = client.post("/recommend", json={})
        assert r.status_code == 422

    def test_malformed_json_returns_422(self, client):
        r = client.post(
            "/recommend",
            content="not json at all",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 422

    def test_filters_passed_through(self, client):
        mock_discover = AsyncMock(return_value=MOCK_MOVIES)
        mocks = [
            patch("main.interpret_mood", new_callable=AsyncMock, return_value=MOCK_PARAMS),
            patch("main.discover_movies", mock_discover),
            patch("main.get_movie_detail", new_callable=AsyncMock, return_value=MOCK_DETAIL),
            patch("main.enrich_with_omdb", new_callable=AsyncMock, return_value=MOCK_OMDB),
        ]
        for m in mocks:
            m.start()
        try:
            client.post("/recommend", json={
                "mood": "fun",
                "original_language": "ko",
                "exclude_animation": True,
                "min_year": 2015,
            })
            call_kwargs = mock_discover.call_args
            filters = call_kwargs.kwargs.get("filters") or call_kwargs[1].get("filters")
            assert filters["original_language"] == "ko"
            assert filters["exclude_animation"] is True
            assert filters["min_year"] == 2015
        finally:
            for m in mocks:
                m.stop()

    def test_default_filters_are_none(self, client):
        mock_discover = AsyncMock(return_value=MOCK_MOVIES)
        mocks = [
            patch("main.interpret_mood", new_callable=AsyncMock, return_value=MOCK_PARAMS),
            patch("main.discover_movies", mock_discover),
            patch("main.get_movie_detail", new_callable=AsyncMock, return_value=MOCK_DETAIL),
            patch("main.enrich_with_omdb", new_callable=AsyncMock, return_value=MOCK_OMDB),
        ]
        for m in mocks:
            m.start()
        try:
            client.post("/recommend", json={"mood": "fun"})
            call_kwargs = mock_discover.call_args
            filters = call_kwargs.kwargs.get("filters") or call_kwargs[1].get("filters")
            assert filters["original_language"] is None
            assert filters["exclude_animation"] is False
            assert filters["min_year"] is None
        finally:
            for m in mocks:
                m.stop()


class TestRecommendGroupEndpoint:

    def test_valid_group_moods_returns_results(self, client):
        mocks = _service_mocks()
        for m in mocks:
            m.start()
        try:
            r = client.post("/recommend-group", json={"moods": ["scary", "romantic"]})
            assert r.status_code == 200
            assert len(r.json()["results"]) > 0
        finally:
            for m in mocks:
                m.stop()

    def test_empty_moods_array_returns_422(self, client):
        r = client.post("/recommend-group", json={"moods": []})
        assert r.status_code == 422

    def test_five_moods_returns_422(self, client):
        r = client.post("/recommend-group", json={"moods": ["a", "b", "c", "d", "e"]})
        assert r.status_code == 422

    def test_single_mood_in_group_is_valid(self, client):
        mocks = _service_mocks()
        for m in mocks:
            m.start()
        try:
            r = client.post("/recommend-group", json={"moods": ["fun"]})
            assert r.status_code == 200
        finally:
            for m in mocks:
                m.stop()

    def test_mood_in_array_too_long_returns_422(self, client):
        r = client.post("/recommend-group", json={"moods": ["ok", "a" * 501]})
        assert r.status_code == 422


class TestRateLimiting:

    def test_recommend_rate_limit(self, client):
        mocks = _service_mocks()
        for m in mocks:
            m.start()
        try:
            statuses = []
            for _ in range(11):
                r = client.post("/recommend", json={"mood": "test"})
                statuses.append(r.status_code)
            assert 429 in statuses
            assert statuses.count(200) <= 10
        finally:
            for m in mocks:
                m.stop()

    def test_group_rate_limit(self, client):
        mocks = _service_mocks()
        for m in mocks:
            m.start()
        try:
            statuses = []
            for _ in range(6):
                r = client.post("/recommend-group", json={"moods": ["test"]})
                statuses.append(r.status_code)
            assert 429 in statuses
            assert statuses.count(200) <= 5
        finally:
            for m in mocks:
                m.stop()


class TestErrorHandling:

    def test_internal_error_returns_generic_message(self):
        error_client = TestClient(app, raise_server_exceptions=False)
        with patch("main.interpret_mood", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            r = error_client.post("/recommend", json={"mood": "test"})

        assert r.status_code == 500
        assert r.json() == {"error": "Something went wrong. Please try again."}

    def test_no_stack_trace_in_error_response(self):
        error_client = TestClient(app, raise_server_exceptions=False)
        with patch("main.interpret_mood", new_callable=AsyncMock, side_effect=RuntimeError("secret crash")):
            r = error_client.post("/recommend", json={"mood": "test"})

        body = r.text
        assert "Traceback" not in body
        assert "secret crash" not in body
        assert "main.py" not in body
        assert "mood.py" not in body


class TestCorsOnErrors:

    def test_500_response_keeps_cors_header(self):
        error_client = TestClient(app, raise_server_exceptions=False)
        with patch("main.interpret_mood", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            r = error_client.post(
                "/recommend", json={"mood": "test"},
                headers={"Origin": "https://job-joseph.com"},
            )
        assert r.status_code == 500
        assert r.headers.get("access-control-allow-origin") == "https://job-joseph.com"

    def test_unknown_origin_gets_no_cors_header(self, client):
        r = client.get("/", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in r.headers

    def test_crash_is_logged(self, caplog):
        error_client = TestClient(app, raise_server_exceptions=False)
        with patch("main.interpret_mood", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            error_client.post("/recommend", json={"mood": "test"})
        assert any("Unhandled error on POST /recommend" in r.message for r in caplog.records)


class TestLogRedaction:

    def test_api_keys_redacted_from_log_lines(self):
        import logging
        from main import _RedactingFormatter
        record = logging.LogRecord(
            "hugin.test", logging.WARNING, __file__, 1,
            "GET https://api.example/x?api_key=SECRET1&page=2 and ?apikey=SECRET2", None, None,
        )
        line = _RedactingFormatter("%(message)s").format(record)
        assert "SECRET1" not in line and "SECRET2" not in line
        assert "page=2" in line


class TestServiceEndpoints:

    def test_head_on_root_for_uptime_checks(self, client):
        assert client.head("/").status_code == 200

    @pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
    def test_api_docs_not_public(self, client, path):
        assert client.get(path).status_code == 404


class TestFilterValidation:

    @pytest.mark.parametrize("body", [
        {"mood": "x", "page": -1},
        {"mood": "x", "page": 10_001},
        {"mood": "x", "min_year": -5},
        {"mood": "x", "min_year": 99999},
        {"mood": "x", "original_language": "korean"},
        {"mood": "x", "original_language": "!!"},
    ])
    def test_invalid_filters_return_422(self, client, body):
        assert client.post("/recommend", json=body).status_code == 422

    def test_group_endpoint_validates_filters_too(self, client):
        r = client.post("/recommend-group", json={"moods": ["x"], "page": -1})
        assert r.status_code == 422

    @pytest.mark.parametrize("extra, expected_filters, expected_page", [
        ({"page": 0, "min_year": 0, "original_language": ""}, {"original_language": None, "min_year": None}, None),
        ({"original_language": "Any"}, {"original_language": None}, None),
        ({"original_language": " KO ", "page": 3}, {"original_language": "ko"}, 3),
    ])
    def test_empty_values_mean_no_filter(self, client, extra, expected_filters, expected_page):
        mock_discover = AsyncMock(return_value=MOCK_MOVIES)
        with patch("main.interpret_mood", new_callable=AsyncMock, return_value=dict(MOCK_PARAMS)), \
             patch("main.discover_movies", mock_discover), \
             patch("main.get_movie_detail", new_callable=AsyncMock, return_value=MOCK_DETAIL), \
             patch("main.enrich_with_omdb", new_callable=AsyncMock, return_value=MOCK_OMDB):
            r = client.post("/recommend", json={"mood": "fun", **extra})

        assert r.status_code == 200
        kwargs = mock_discover.call_args.kwargs
        for key, value in expected_filters.items():
            assert kwargs["filters"][key] == value
        assert kwargs["page"] == expected_page


class TestEnrichmentFailures:

    def test_failed_lookups_still_return_movies(self, client):
        with patch("main.interpret_mood", new_callable=AsyncMock, return_value=dict(MOCK_PARAMS)), \
             patch("main.discover_movies", new_callable=AsyncMock, return_value=MOCK_MOVIES), \
             patch("main.get_movie_detail", new_callable=AsyncMock, return_value={}), \
             patch("main.enrich_with_omdb", new_callable=AsyncMock, return_value={}):
            r = client.post("/recommend", json={"mood": "fun"})

        assert r.status_code == 200
        assert [m["title"] for m in r.json()["results"]] == [m["title"] for m in MOCK_MOVIES]
