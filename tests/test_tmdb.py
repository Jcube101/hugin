import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from tmdb import discover_movies, get_movie_detail


def _mock_httpx_response(json_data, status_code=200):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=response
        )
    return response


@pytest.fixture
def captured_query():
    """Capture the query params passed to the mocked httpx client."""
    queries = []

    async def mock_get(url, params=None):
        queries.append({"url": url, "params": params or {}})
        return _mock_httpx_response({"results": [
            {"id": i + 1, "title": f"Movie {i + 1}"} for i in range(5)
        ]})

    return queries, mock_get


class TestDiscoverMovies:

    @pytest.mark.asyncio
    async def test_basic_query_includes_required_params(self, captured_query):
        queries, mock_get = captured_query
        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            await discover_movies({"genres": [35], "sort_by": "popularity.desc"})

        params = queries[0]["params"]
        assert params["vote_count.gte"] == 50
        assert params["language"] == "en-US"
        assert "api_key" in params

    @pytest.mark.asyncio
    async def test_genre_params_passed_correctly(self, captured_query):
        queries, mock_get = captured_query
        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            await discover_movies({"genres": [28, 53], "sort_by": "popularity.desc"})

        params = queries[0]["params"]
        assert params["with_genres"] == "28,53"

    @pytest.mark.asyncio
    async def test_vote_floor_applied(self, captured_query):
        queries, mock_get = captured_query
        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            await discover_movies({"genres": [35], "vote_floor": 7.5, "sort_by": "popularity.desc"})

        params = queries[0]["params"]
        assert params["vote_average.gte"] == 7.5

    @pytest.mark.asyncio
    async def test_gem_mode_adds_vote_count_ceiling(self, captured_query):
        queries, mock_get = captured_query
        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            await discover_movies({"genres": [53], "gem_mode": True, "sort_by": "vote_average.desc"})

        params = queries[0]["params"]
        assert params["vote_count.lte"] == 3000
        assert params["vote_average.gte"] == 7.5

    @pytest.mark.asyncio
    async def test_gem_mode_uses_only_first_genre(self, captured_query):
        queries, mock_get = captured_query
        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            await discover_movies({"genres": [53, 9648, 18], "gem_mode": True, "sort_by": "vote_average.desc"})

        params = queries[0]["params"]
        assert params["with_genres"] == "53"

    @pytest.mark.asyncio
    async def test_language_filter_applied(self, captured_query):
        queries, mock_get = captured_query
        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            await discover_movies(
                {"genres": [35], "sort_by": "popularity.desc"},
                filters={"original_language": "ko"},
            )

        params = queries[0]["params"]
        assert params["with_original_language"] == "ko"

    @pytest.mark.asyncio
    async def test_exclude_animation_adds_without_genres(self, captured_query):
        queries, mock_get = captured_query
        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            await discover_movies(
                {"genres": [35], "sort_by": "popularity.desc"},
                filters={"exclude_animation": True},
            )

        params = queries[0]["params"]
        assert params["without_genres"] == "16"

    @pytest.mark.asyncio
    async def test_min_year_filter_applied(self, captured_query):
        queries, mock_get = captured_query
        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            await discover_movies(
                {"genres": [35], "sort_by": "popularity.desc"},
                filters={"min_year": 2010},
            )

        params = queries[0]["params"]
        assert params["primary_release_date.gte"] == "2010-01-01"

    @pytest.mark.asyncio
    async def test_all_filters_combined(self, captured_query):
        queries, mock_get = captured_query
        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            await discover_movies(
                {"genres": [35], "sort_by": "popularity.desc"},
                filters={
                    "original_language": "hi",
                    "exclude_animation": True,
                    "min_year": 2015,
                },
            )

        params = queries[0]["params"]
        assert params["with_original_language"] == "hi"
        assert params["without_genres"] == "16"
        assert params["primary_release_date.gte"] == "2015-01-01"

    @pytest.mark.asyncio
    async def test_no_filters_no_extra_params(self, captured_query):
        queries, mock_get = captured_query
        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            await discover_movies({"genres": [35], "sort_by": "popularity.desc"})

        params = queries[0]["params"]
        assert "without_genres" not in params
        assert "with_original_language" not in params
        assert "primary_release_date.gte" not in params

    @pytest.mark.asyncio
    async def test_returns_correct_number_of_results(self):
        async def mock_get(url, params=None):
            return _mock_httpx_response({"results": [
                {"id": i + 1, "title": f"Movie {i + 1}"} for i in range(10)
            ]})

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            results = await discover_movies(
                {"genres": [35], "sort_by": "popularity.desc"}, limit=3
            )

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_empty_tmdb_response_returns_empty_list(self):
        async def mock_get(url, params=None):
            return _mock_httpx_response({"results": []})

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            results = await discover_movies({"genres": [35], "sort_by": "popularity.desc"})

        assert results == []

    @pytest.mark.asyncio
    async def test_page_randomisation_within_bounds(self):
        pages_seen = set()

        async def mock_get(url, params=None):
            pages_seen.add(params.get("page"))
            return _mock_httpx_response({"results": [{"id": 1, "title": "M"}]})

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            for _ in range(50):
                await discover_movies({"genres": [35], "sort_by": "popularity.desc"})

        assert pages_seen.issubset({1, 2, 3, 4, 5})
        assert len(pages_seen) >= 2

    @pytest.mark.asyncio
    async def test_gem_mode_page_capped_at_2(self):
        pages_seen = set()

        async def mock_get(url, params=None):
            pages_seen.add(params.get("page"))
            return _mock_httpx_response({"results": [{"id": 1, "title": "M"}]})

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            for _ in range(50):
                await discover_movies({"genres": [35], "gem_mode": True, "sort_by": "vote_average.desc"})

        assert pages_seen.issubset({1, 2})


class TestGetMovieDetail:

    @pytest.mark.asyncio
    async def test_returns_imdb_id(self, mock_tmdb_detail_response):
        async def mock_get(url, params=None):
            return _mock_httpx_response(mock_tmdb_detail_response)

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            result = await get_movie_detail(123)

        assert result["imdb_id"] == "tt1234567"

    @pytest.mark.asyncio
    async def test_returns_runtime(self, mock_tmdb_detail_response):
        async def mock_get(url, params=None):
            return _mock_httpx_response(mock_tmdb_detail_response)

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            result = await get_movie_detail(123)

        assert result["runtime"] == 120

    @pytest.mark.asyncio
    async def test_returns_genres_as_names(self, mock_tmdb_detail_response):
        async def mock_get(url, params=None):
            return _mock_httpx_response(mock_tmdb_detail_response)

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            result = await get_movie_detail(123)

        assert result["genres"] == ["Comedy", "Drama"]

    @pytest.mark.asyncio
    async def test_missing_imdb_id_returns_none(self):
        async def mock_get(url, params=None):
            return _mock_httpx_response({
                "runtime": 90,
                "tagline": "No IMDB",
                "genres": [],
            })

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            result = await get_movie_detail(999)

        assert result["imdb_id"] is None
