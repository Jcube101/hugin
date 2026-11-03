import pytest
from unittest.mock import MagicMock, patch
import httpx

import omdb
from omdb import enrich_with_omdb, get_omdb_call_count


@pytest.fixture(autouse=True)
def reset_omdb_counter():
    """Reset OMDb call counter before each test."""
    omdb._call_count = 0
    omdb._call_date = None
    yield


def _mock_httpx_response(json_data, status_code=200):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_data
    return response


class TestEnrichWithOmdb:

    @pytest.mark.asyncio
    async def test_extracts_imdb_rating(self):
        async def mock_get(url, params=None, **kwargs):
            return _mock_httpx_response({
                "imdbRating": "8.4",
                "Rated": "PG-13",
                "Ratings": [
                    {"Source": "Internet Movie Database", "Value": "8.4/10"},
                    {"Source": "Rotten Tomatoes", "Value": "92%"},
                ],
            })

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("omdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"OMDB_API_KEY": "test-key"}):
            result = await enrich_with_omdb("tt0032553")

        assert result["imdb_rating"] == "8.4"

    @pytest.mark.asyncio
    async def test_extracts_rt_score(self):
        async def mock_get(url, params=None, **kwargs):
            return _mock_httpx_response({
                "imdbRating": "7.5",
                "Rated": "R",
                "Ratings": [
                    {"Source": "Internet Movie Database", "Value": "7.5/10"},
                    {"Source": "Rotten Tomatoes", "Value": "85%"},
                    {"Source": "Metacritic", "Value": "72/100"},
                ],
            })

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("omdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"OMDB_API_KEY": "test-key"}):
            result = await enrich_with_omdb("tt1234567")

        assert result["rt_score"] == "85%"

    @pytest.mark.asyncio
    async def test_no_rt_score_returns_none(self):
        async def mock_get(url, params=None, **kwargs):
            return _mock_httpx_response({
                "imdbRating": "7.0",
                "Rated": "PG",
                "Ratings": [
                    {"Source": "Internet Movie Database", "Value": "7.0/10"},
                ],
            })

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("omdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"OMDB_API_KEY": "test-key"}):
            result = await enrich_with_omdb("tt9999999")

        assert result["rt_score"] is None

    @pytest.mark.asyncio
    async def test_empty_imdb_id_returns_empty_dict(self):
        result = await enrich_with_omdb(None)
        assert result == {}

    @pytest.mark.asyncio
    async def test_empty_string_imdb_id_returns_empty_dict(self):
        result = await enrich_with_omdb("")
        assert result == {}

    @pytest.mark.asyncio
    async def test_http_error_returns_empty_dict(self):
        async def mock_get(url, params=None, **kwargs):
            return _mock_httpx_response({}, status_code=500)

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("omdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"OMDB_API_KEY": "test-key"}):
            result = await enrich_with_omdb("tt0000001")

        assert result == {}

    @pytest.mark.asyncio
    async def test_rated_field_extracted(self):
        async def mock_get(url, params=None, **kwargs):
            return _mock_httpx_response({
                "imdbRating": "6.5",
                "Rated": "R",
                "Ratings": [],
            })

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("omdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"OMDB_API_KEY": "test-key"}):
            result = await enrich_with_omdb("tt5555555")

        assert result["rated"] == "R"

    @pytest.mark.asyncio
    async def test_empty_ratings_array(self):
        async def mock_get(url, params=None, **kwargs):
            return _mock_httpx_response({
                "imdbRating": "5.0",
                "Rated": "PG",
                "Ratings": [],
            })

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("omdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"OMDB_API_KEY": "test-key"}):
            result = await enrich_with_omdb("tt1111111")

        assert result["rt_score"] is None
        assert result["imdb_rating"] == "5.0"


class TestOmdbDailyLimit:

    @pytest.mark.asyncio
    async def test_skips_call_when_limit_reached(self):
        omdb._call_count = omdb.OMDB_DAILY_LIMIT
        omdb._call_date = "2026-05-08"

        with patch("omdb.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2026-05-08"
            mock_dt.side_effect = lambda *a, **k: omdb.datetime(*a, **k)
            result = await enrich_with_omdb("tt1234567")

        assert result == {}

    @pytest.mark.asyncio
    async def test_counter_increments_on_call(self):
        async def mock_get(url, params=None, **kwargs):
            return _mock_httpx_response({
                "imdbRating": "7.0", "Rated": "PG", "Ratings": [],
            })

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("omdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"OMDB_API_KEY": "test-key"}):
            await enrich_with_omdb("tt0000001")
            assert omdb._call_count == 1
            await enrich_with_omdb("tt0000002")
            assert omdb._call_count == 2

    def test_get_omdb_call_count_returns_dict(self):
        info = get_omdb_call_count()
        assert "calls" in info
        assert "limit" in info
        assert "date" in info
        assert info["calls"] == 0
        assert info["limit"] == omdb.OMDB_DAILY_LIMIT

    @pytest.mark.asyncio
    async def test_counter_resets_on_new_day(self):
        omdb._call_count = 500
        omdb._call_date = "2000-01-01"

        info = get_omdb_call_count()
        assert info["calls"] == 0
        assert info["date"] != "2000-01-01"


class TestOmdbHardening:

    def test_uses_https(self):
        assert omdb.OMDB_BASE.startswith("https://")

    @pytest.mark.parametrize("failure", [
        httpx.ConnectError("refused"),
        httpx.RemoteProtocolError("reset"),
        httpx.ReadTimeout("slow"),
    ])
    @pytest.mark.asyncio
    async def test_network_errors_return_empty_dict(self, failure):
        async def mock_get(url, params=None, **kwargs):
            raise failure

        mock_client = MagicMock()
        mock_client.get = mock_get
        with patch("omdb._get_client", return_value=mock_client):
            assert await enrich_with_omdb("tt0000001") == {}

    @pytest.mark.asyncio
    async def test_not_found_response_returns_empty_dict(self):
        async def mock_get(url, params=None, **kwargs):
            return _mock_httpx_response({"Response": "False", "Error": "Incorrect IMDb ID."})

        mock_client = MagicMock()
        mock_client.get = mock_get
        with patch("omdb._get_client", return_value=mock_client):
            assert await enrich_with_omdb("tt0000001") == {}

    @pytest.mark.asyncio
    async def test_invalid_json_returns_empty_dict(self):
        response = _mock_httpx_response({})
        response.json.side_effect = ValueError("not json")

        async def mock_get(url, params=None, **kwargs):
            return response

        mock_client = MagicMock()
        mock_client.get = mock_get
        with patch("omdb._get_client", return_value=mock_client):
            assert await enrich_with_omdb("tt0000001") == {}

    @pytest.mark.asyncio
    async def test_parallel_calls_cannot_overshoot_daily_cap(self):
        import asyncio
        sent = []

        async def mock_get(url, params=None, **kwargs):
            sent.append(params["i"])
            await asyncio.sleep(0.01)
            return _mock_httpx_response({"imdbRating": "7.0", "Ratings": []})

        mock_client = MagicMock()
        mock_client.get = mock_get
        omdb._reset_if_new_day()
        omdb._call_count = omdb.OMDB_DAILY_LIMIT - 1
        with patch("omdb._get_client", return_value=mock_client):
            await asyncio.gather(*[enrich_with_omdb(f"tt{i}") for i in range(5)])

        assert len(sent) == 1
        assert omdb._call_count == omdb.OMDB_DAILY_LIMIT


class TestOmdbCache:

    @pytest.mark.asyncio
    async def test_repeat_lookup_uses_cache_and_does_not_count(self):
        sent = []

        async def mock_get(url, params=None, **kwargs):
            sent.append(params["i"])
            return _mock_httpx_response({"imdbRating": "8.1", "Rated": "PG", "Ratings": []})

        mock_client = MagicMock()
        mock_client.get = mock_get
        with patch("omdb._get_client", return_value=mock_client):
            first = await enrich_with_omdb("tt0000001")
            second = await enrich_with_omdb("tt0000001")

        assert first == second == {"imdb_rating": "8.1", "rt_score": None, "rated": "PG"}
        assert sent == ["tt0000001"]
        assert omdb._call_count == 1

    @pytest.mark.asyncio
    async def test_cached_ratings_still_served_after_daily_cap(self):
        async def mock_get(url, params=None, **kwargs):
            return _mock_httpx_response({"imdbRating": "7.0", "Ratings": []})

        mock_client = MagicMock()
        mock_client.get = mock_get
        with patch("omdb._get_client", return_value=mock_client):
            await enrich_with_omdb("tt0000001")
            omdb._call_count = omdb.OMDB_DAILY_LIMIT
            assert (await enrich_with_omdb("tt0000001"))["imdb_rating"] == "7.0"
            assert await enrich_with_omdb("tt0000002") == {}

    @pytest.mark.asyncio
    async def test_failures_are_not_cached(self):
        responses = [
            _mock_httpx_response({}, status_code=500),
            _mock_httpx_response({"imdbRating": "6.0", "Ratings": []}),
        ]

        async def mock_get(url, params=None, **kwargs):
            return responses.pop(0)

        mock_client = MagicMock()
        mock_client.get = mock_get
        with patch("omdb._get_client", return_value=mock_client):
            assert await enrich_with_omdb("tt0000001") == {}
            assert (await enrich_with_omdb("tt0000001"))["imdb_rating"] == "6.0"
