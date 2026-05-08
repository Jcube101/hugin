import pytest
from unittest.mock import MagicMock, patch
import httpx

from omdb import enrich_with_omdb


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
