import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

import tmdb
from tmdb import discover_movies, get_movie_detail


def _mock_httpx_response(json_data, status_code=200, headers=None):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.headers = headers or {}
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

    async def mock_get(url, params=None, **kwargs):
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
        assert params["vote_count.gte"] == tmdb.MIN_VOTES
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
        async def mock_get(url, params=None, **kwargs):
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
        async def mock_get(url, params=None, **kwargs):
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

        async def mock_get(url, params=None, **kwargs):
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

        async def mock_get(url, params=None, **kwargs):
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
        async def mock_get(url, params=None, **kwargs):
            return _mock_httpx_response(mock_tmdb_detail_response)

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            result = await get_movie_detail(123)

        assert result["imdb_id"] == "tt1234567"

    @pytest.mark.asyncio
    async def test_returns_runtime(self, mock_tmdb_detail_response):
        async def mock_get(url, params=None, **kwargs):
            return _mock_httpx_response(mock_tmdb_detail_response)

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            result = await get_movie_detail(123)

        assert result["runtime"] == 120

    @pytest.mark.asyncio
    async def test_returns_genres_as_names(self, mock_tmdb_detail_response):
        async def mock_get(url, params=None, **kwargs):
            return _mock_httpx_response(mock_tmdb_detail_response)

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("tmdb._get_client", return_value=mock_client), \
             patch.dict("os.environ", {"TMDB_API_KEY": "test-key"}):
            result = await get_movie_detail(123)

        assert result["genres"] == ["Comedy", "Drama"]

    @pytest.mark.asyncio
    async def test_missing_imdb_id_returns_none(self):
        async def mock_get(url, params=None, **kwargs):
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


def _client_with(get_fn):
    mock_client = MagicMock()
    mock_client.get = get_fn
    return mock_client


def _movies(start, count):
    return [{"id": i, "title": f"Movie {i}"} for i in range(start, start + count)]


class TestFallbackSteps:

    @pytest.mark.asyncio
    async def test_tops_up_from_any_genre_when_every_genre_is_short(self):
        calls = []

        async def mock_get(url, params=None, **kwargs):
            calls.append(params["with_genres"])
            if "," in params["with_genres"]:  # every genre: only 2 films exist
                return _mock_httpx_response({"results": _movies(1, 2), "total_pages": 1})
            return _mock_httpx_response({"results": _movies(1, 2) + _movies(10, 20), "total_pages": 50})

        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            results = await discover_movies({"genres": [27, 10749]}, page=1)

        assert calls == ["27,10749", "27|10749"]
        assert [m["id"] for m in results] == [1, 2, 10, 11, 12]  # exact matches first, no duplicates

    @pytest.mark.asyncio
    async def test_stops_after_first_step_when_it_has_enough(self):
        calls = []

        async def mock_get(url, params=None, **kwargs):
            calls.append(params)
            return _mock_httpx_response({"results": _movies(1, 20), "total_pages": 10})

        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            await discover_movies({"genres": [35, 18]}, page=1)

        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_last_step_relaxes_rating_and_votes_but_keeps_filters(self):
        calls = []

        async def mock_get(url, params=None, **kwargs):
            calls.append(params)
            return _mock_httpx_response({"results": [], "total_pages": 0})

        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            results = await discover_movies(
                {"genres": [35], "vote_floor": 7.5}, filters={"original_language": "ko"}, page=1
            )

        assert results == []
        last = calls[-1]
        assert last["vote_average.gte"] == tmdb.RELAXED_RATING
        assert last["vote_count.gte"] == tmdb.RELAXED_MIN_VOTES
        assert last["with_original_language"] == "ko"

    @pytest.mark.asyncio
    async def test_no_genres_sends_no_genre_filter(self, captured_query):
        queries, mock_get = captured_query
        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            await discover_movies({"genres": []})
        assert "with_genres" not in queries[0]["params"]


class TestGemMode:

    @pytest.mark.asyncio
    async def test_gem_results_returned_and_flag_kept(self):
        calls = []

        async def mock_get(url, params=None, **kwargs):
            calls.append(params)
            return _mock_httpx_response({"results": _movies(1, 3), "total_pages": 1})

        params = {"genres": [53], "gem_mode": True}
        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            results = await discover_movies(params)

        assert len(calls) == 1
        assert calls[0]["vote_count.gte"] == tmdb.GEM_MIN_VOTES
        assert calls[0]["vote_count.lte"] == tmdb.GEM_MAX_VOTES
        assert len(results) == 3
        assert params["gem_mode"] is True

    @pytest.mark.asyncio
    async def test_empty_gem_search_falls_back_and_clears_flag(self):
        async def mock_get(url, params=None, **kwargs):
            if "vote_count.lte" in params:
                return _mock_httpx_response({"results": [], "total_pages": 0})
            return _mock_httpx_response({"results": _movies(1, 20), "total_pages": 5})

        params = {"genres": [53, 18], "gem_mode": True}
        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            results = await discover_movies(params)

        assert len(results) == 5
        assert params["gem_mode"] is False


class TestPaging:

    @pytest.mark.asyncio
    async def test_page_past_the_end_wraps_round(self):
        pages = []

        async def mock_get(url, params=None, **kwargs):
            pages.append(params["page"])
            if params["page"] > 2:
                return _mock_httpx_response({"results": [], "total_pages": 2})
            return _mock_httpx_response({"results": _movies(1, 20), "total_pages": 2})

        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            results = await discover_movies({"genres": [35]}, filters={"min_year": 2015}, page=7)

        assert pages == [7, 1]  # (7 - 1) % 2 + 1
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_explicit_page_is_honoured_with_filters(self, captured_query):
        # The old code capped every filtered "try again" at page 2
        queries, mock_get = captured_query
        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            await discover_movies({"genres": [35]}, filters={"original_language": "ko"}, page=4)
        assert queries[0]["params"]["page"] == 4

    @pytest.mark.asyncio
    async def test_page_beyond_tmdb_max_is_wrapped_into_range(self, captured_query):
        queries, mock_get = captured_query
        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            await discover_movies({"genres": [35]}, page=501)
        assert queries[0]["params"]["page"] == 1


class TestRetries:

    @pytest.mark.asyncio
    async def test_429_with_date_retry_after_retries_after_short_wait(self):
        responses = [
            _mock_httpx_response({}, 429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
            _mock_httpx_response({"imdb_id": "tt1", "genres": []}),
        ]

        async def mock_get(url, params=None, **kwargs):
            return responses.pop(0)

        with patch("tmdb._get_client", return_value=_client_with(mock_get)), \
             patch("tmdb.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await get_movie_detail(1)

        assert result["imdb_id"] == "tt1"
        assert mock_sleep.call_args.args[0] == 2.0

    @pytest.mark.asyncio
    async def test_long_retry_after_is_capped(self):
        responses = [
            _mock_httpx_response({}, 429, headers={"Retry-After": "3600"}),
            _mock_httpx_response({"imdb_id": "tt1", "genres": []}),
        ]

        async def mock_get(url, params=None, **kwargs):
            return responses.pop(0)

        with patch("tmdb._get_client", return_value=_client_with(mock_get)), \
             patch("tmdb.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await get_movie_detail(1)

        assert mock_sleep.call_args.args[0] == tmdb.MAX_RETRY_AFTER

    @pytest.mark.asyncio
    async def test_503_retried_once(self):
        responses = [
            _mock_httpx_response({}, 503),
            _mock_httpx_response({"results": _movies(1, 20), "total_pages": 3}),
        ]

        async def mock_get(url, params=None, **kwargs):
            return responses.pop(0)

        with patch("tmdb._get_client", return_value=_client_with(mock_get)), \
             patch("tmdb.asyncio.sleep", new_callable=AsyncMock):
            results = await discover_movies({"genres": [35]}, page=1)

        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_requests_use_short_connect_timeout(self):
        timeouts = []

        async def mock_get(url, params=None, **kwargs):
            timeouts.append(kwargs["timeout"])
            return _mock_httpx_response({"results": _movies(1, 20), "total_pages": 3})

        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            await discover_movies({"genres": [35]}, page=1)

        assert timeouts[0].connect == tmdb.CONNECT_TIMEOUT
        assert timeouts[0].read == tmdb.REQUEST_TIMEOUT


class TestTMDbUnreachable:

    @pytest.mark.parametrize("failure", [
        httpx.RemoteProtocolError("connection reset"),
        httpx.ConnectError("TLS handshake failed"),
        httpx.ConnectTimeout("no answer"),
        httpx.ReadTimeout("slow"),
    ])
    @pytest.mark.asyncio
    async def test_raises_instead_of_returning_empty_list(self, failure):
        async def mock_get(url, params=None, **kwargs):
            raise failure

        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            with pytest.raises(tmdb.TMDbUnavailable):
                await discover_movies({"genres": [35, 18]})

    @pytest.mark.asyncio
    async def test_stops_after_first_unreachable_call(self):
        # Looser searches won't help if TMDb is down — don't make the user wait for them
        calls = []

        async def mock_get(url, params=None, **kwargs):
            calls.append(params)
            raise httpx.ConnectError("down")

        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            with pytest.raises(tmdb.TMDbUnavailable):
                await discover_movies({"genres": [35, 18]})

        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_returns_partial_results_if_tmdb_drops_out_midway(self):
        async def mock_get(url, params=None, **kwargs):
            if "," in params["with_genres"]:
                return _mock_httpx_response({"results": _movies(1, 2), "total_pages": 1})
            raise httpx.ConnectError("down")

        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            results = await discover_movies({"genres": [27, 10749]}, page=1)

        assert [m["id"] for m in results] == [1, 2]

    @pytest.mark.asyncio
    async def test_reached_but_empty_still_returns_empty_list(self):
        # TMDb answered: there genuinely are no matches. That's not an outage.
        async def mock_get(url, params=None, **kwargs):
            return _mock_httpx_response({"results": [], "total_pages": 0})

        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            assert await discover_movies({"genres": [35]}) == []

    @pytest.mark.asyncio
    async def test_unreachable_gem_search_raises_without_falling_back(self):
        calls = []

        async def mock_get(url, params=None, **kwargs):
            calls.append(params)
            raise httpx.ConnectError("down")

        params = {"genres": [53], "gem_mode": True}
        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            with pytest.raises(tmdb.TMDbUnavailable):
                await discover_movies(params)

        assert len(calls) == 1
        assert params["gem_mode"] is True  # not "no gems found" — TMDb never answered

    @pytest.mark.asyncio
    async def test_unreachable_wrap_round_call_raises(self):
        responses = [_mock_httpx_response({"results": [], "total_pages": 2})]

        async def mock_get(url, params=None, **kwargs):
            if responses:
                return responses.pop(0)
            raise httpx.ConnectError("down")

        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            with pytest.raises(tmdb.TMDbUnavailable):
                await discover_movies({"genres": [35]}, page=7)

    @pytest.mark.asyncio
    async def test_discover_bad_api_key_still_raises(self):
        async def mock_get(url, params=None, **kwargs):
            return _mock_httpx_response({}, 401)

        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            with pytest.raises(httpx.HTTPStatusError):
                await discover_movies({"genres": [35]})


class TestDetailFailures:

    @pytest.mark.parametrize("failure", [
        httpx.ConnectError("refused"),
        httpx.RemoteProtocolError("reset"),
        httpx.ReadTimeout("slow"),
    ])
    @pytest.mark.asyncio
    async def test_network_errors_return_empty_dict(self, failure):
        async def mock_get(url, params=None, **kwargs):
            raise failure

        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            assert await get_movie_detail(1) == {}

    @pytest.mark.asyncio
    async def test_404_returns_empty_dict(self):
        async def mock_get(url, params=None, **kwargs):
            return _mock_httpx_response({}, 404)

        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            assert await get_movie_detail(1) == {}

    @pytest.mark.asyncio
    async def test_invalid_json_returns_empty_dict(self):
        response = _mock_httpx_response({})
        response.json.side_effect = ValueError("not json")

        async def mock_get(url, params=None, **kwargs):
            return response

        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            assert await get_movie_detail(1) == {}
