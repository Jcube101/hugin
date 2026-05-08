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
        async def mock_get(url, params=None):
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
        async def mock_get(url, params=None):
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
        async def mock_get(url, params=None):
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
        async def mock_get(url, params=None):
            return _mock_httpx_response({}, status_code=500)

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("omdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"OMDB_API_KEY": "test-key"}):
            result = await enrich_with_omdb("tt0000001")

        assert result == {}

    @pytest.mark.asyncio
    async def test_rated_field_extracted(self):
        async def mock_get(url, params=None):
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
        async def mock_get(url, params=None):
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
        async def mock_get(url, params=None):
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
        omdb._call_date = "2026-05-07"

        info = get_omdb_call_count()
        assert info["calls"] == 0
        assert info["date"] == "2026-05-08"
