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
            results = await discover_movies(params, page=1)

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


def _router(keywords=None, discover=None, detail=None, calls=None):
    """A fake TMDb: routes by URL. `discover(params) -> json`."""
    keywords = keywords or {}

    async def mock_get(url, params=None, **kwargs):
        if calls is not None:
            calls.append((url.rsplit("/3", 1)[-1], dict(params or {})))
        if "/search/keyword" in url:
            name = keywords.get(params["query"])
            return _mock_httpx_response({"results": [{"id": name[0], "name": name[1]}] if name else []})
        if "/discover/movie" in url:
            return _mock_httpx_response(discover(params))
        return _mock_httpx_response(detail or {})
    return mock_get


class TestKeywords:

    @pytest.mark.asyncio
    async def test_exact_tag_matches_resolve_and_others_are_dropped(self):
        kw = {"heist": (10051, "heist"), "witty dialogue": (999, "witty dialogue banter")}
        with patch("tmdb._get_client", return_value=_client_with(_router(keywords=kw))):
            assert await tmdb.resolve_keywords(["Heist", "witty dialogue", "nonsense"]) == [10051]

    @pytest.mark.asyncio
    async def test_hyphens_and_spaces_match(self):
        kw = {"mind bending": (4565, "mind-bending")}
        with patch("tmdb._get_client", return_value=_client_with(_router(keywords=kw))):
            assert await tmdb.resolve_keywords(["mind bending"]) == [4565]

    @pytest.mark.asyncio
    async def test_lookups_are_cached_including_misses(self):
        calls = []
        kw = {"heist": (10051, "heist")}
        with patch("tmdb._get_client", return_value=_client_with(_router(keywords=kw, calls=calls))):
            await tmdb.resolve_keywords(["heist", "nonsense"])
            await tmdb.resolve_keywords(["heist", "nonsense"])
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_failed_lookup_is_dropped_and_not_cached(self):
        async def failing(url, params=None, **kwargs):
            raise httpx.ConnectError("down")

        with patch("tmdb._get_client", return_value=_client_with(failing)):
            assert await tmdb.resolve_keywords(["heist"]) == []
        assert tmdb.cache_sizes()["keywords"] == 0

    @pytest.mark.asyncio
    async def test_keyword_step_runs_first_then_genres_top_up(self):
        calls = []

        def discover(params):
            if "with_keywords" in params:
                return {"results": _movies(1, 2), "total_pages": 1}
            return {"results": _movies(100, 20), "total_pages": 9}

        kw = {"heist": (10051, "heist"), "caper": (4344, "caper")}
        with patch("tmdb._get_client", return_value=_client_with(_router(kw, discover, calls=calls))):
            results = await discover_movies({"genres": [80], "keywords": ["heist", "caper"]}, page=1)

        searches = [p for path, p in calls if path == "/discover/movie"]
        assert searches[0]["with_keywords"] == "10051|4344"
        assert searches[0]["with_genres"] == "80"
        assert "with_keywords" not in searches[1]
        assert [m["id"] for m in results] == [1, 2, 100, 101, 102]  # keyword matches first

    @pytest.mark.asyncio
    async def test_no_matched_keywords_means_no_keyword_step(self):
        calls = []

        def discover(params):
            return {"results": _movies(1, 20), "total_pages": 9}

        with patch("tmdb._get_client", return_value=_client_with(_router({}, discover, calls=calls))):
            await discover_movies({"genres": [35], "keywords": ["witty"]}, page=1)

        searches = [p for path, p in calls if path == "/discover/movie"]
        assert len(searches) == 1 and "with_keywords" not in searches[0]


class TestGemSlot:

    @staticmethod
    def _discover(params):
        if "vote_count.lte" in params:  # gem search
            return {"results": [{"id": 3, "title": "Also a standard pick"}, {"id": 900, "title": "Gem"}],
                    "total_pages": 1}
        return {"results": _movies(1, 20), "total_pages": 9}

    @pytest.mark.asyncio
    async def test_four_picks_then_a_gem_last(self):
        with patch("tmdb._get_client", return_value=_client_with(_router({}, self._discover))):
            results = await discover_movies({"genres": [53]}, page=1, gem_slot=True)

        assert [m["id"] for m in results] == [1, 2, 3, 4, 900]  # gem skips id 3, already picked
        assert [m["is_gem"] for m in results] == [False, False, False, False, True]

    @pytest.mark.asyncio
    async def test_no_gem_found_fills_last_slot_with_standard_pick(self):
        def discover(params):
            if "vote_count.lte" in params:
                return {"results": [], "total_pages": 0}
            return {"results": _movies(1, 20), "total_pages": 9}

        with patch("tmdb._get_client", return_value=_client_with(_router({}, discover))):
            results = await discover_movies({"genres": [53]}, page=1, gem_slot=True)

        assert [m["id"] for m in results] == [1, 2, 3, 4, 5]
        assert not any(m["is_gem"] for m in results)

    @pytest.mark.asyncio
    async def test_tmdb_dropping_out_during_gem_search_keeps_standard_picks(self):
        async def mock_get(url, params=None, **kwargs):
            if "vote_count.lte" in params:
                raise httpx.ConnectError("down")
            return _mock_httpx_response({"results": _movies(1, 20), "total_pages": 9})

        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            results = await discover_movies({"genres": [53]}, page=1, gem_slot=True)

        assert [m["id"] for m in results] == [1, 2, 3, 4, 5]

    @pytest.mark.asyncio
    async def test_without_gem_slot_no_gem_search_runs(self):
        calls = []
        with patch("tmdb._get_client", return_value=_client_with(_router({}, self._discover, calls=calls))):
            results = await discover_movies({"genres": [53]}, limit=3, page=1)

        assert not any("vote_count.lte" in p for _, p in calls)
        assert [m["is_gem"] for m in results] == [False, False, False]

    @pytest.mark.asyncio
    async def test_gem_mode_tags_every_pick_as_gem(self):
        def discover(params):
            return {"results": _movies(1, 20), "total_pages": 3}

        with patch("tmdb._get_client", return_value=_client_with(_router({}, discover))):
            results = await discover_movies({"genres": [27], "gem_mode": True}, page=1, gem_slot=True)

        assert len(results) == 5 and all(m["is_gem"] for m in results)

    @pytest.mark.asyncio
    async def test_gem_search_tries_keywords_first(self):
        calls = []

        def discover(params):
            if "vote_count.lte" in params and "with_keywords" in params:
                return {"results": [{"id": 777}], "total_pages": 1}
            return {"results": _movies(1, 20), "total_pages": 9}

        kw = {"heist": (10051, "heist")}
        with patch("tmdb._get_client", return_value=_client_with(_router(kw, discover, calls=calls))):
            results = await discover_movies({"genres": [80], "keywords": ["heist"]}, page=1, gem_slot=True)

        assert results[-1]["id"] == 777 and results[-1]["is_gem"] is True



class TestDetailCache:

    @pytest.mark.asyncio
    async def test_second_lookup_uses_cache(self, mock_tmdb_detail_response):
        calls = []
        router = _router(detail=mock_tmdb_detail_response, calls=calls)
        with patch("tmdb._get_client", return_value=_client_with(router)):
            first = await get_movie_detail(123)
            second = await get_movie_detail(123)
        assert first == second
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_failures_are_not_cached(self, mock_tmdb_detail_response):
        responses = [_mock_httpx_response({}, 404), _mock_httpx_response(mock_tmdb_detail_response)]

        async def mock_get(url, params=None, **kwargs):
            return responses.pop(0)

        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            assert await get_movie_detail(123) == {}
            assert (await get_movie_detail(123))["imdb_id"] == "tt1234567"


class TestQualityKnobs:

    @pytest.mark.asyncio
    async def test_every_search_is_feature_films_only(self):
        calls = []

        def discover(params):
            return {"results": [], "total_pages": 0}

        kw = {"heist": (10051, "heist")}
        with patch("tmdb._get_client", return_value=_client_with(_router(kw, discover, calls=calls))):
            await discover_movies({"genres": [80, 35], "keywords": ["heist"], "gem_mode": True}, page=1)

        searches = [p for path, p in calls if path == "/discover/movie"]
        assert len(searches) > 3
        assert all(p["with_runtime.gte"] == tmdb.MIN_RUNTIME for p in searches)

    @pytest.mark.asyncio
    async def test_keyword_steps_need_a_good_rating_even_if_claude_set_a_low_floor(self):
        calls = []

        def discover(params):
            return {"results": [], "total_pages": 0}

        kw = {"heist": (10051, "heist")}
        with patch("tmdb._get_client", return_value=_client_with(_router(kw, discover, calls=calls))):
            await discover_movies({"genres": [80, 35], "keywords": ["heist"], "vote_floor": 6.0}, page=1)

        searches = [p for path, p in calls if path == "/discover/movie"]
        keyword_steps = [p for p in searches if "with_keywords" in p]
        plain_steps = [p for p in searches if "with_keywords" not in p]
        assert len(keyword_steps) == 2
        assert all(p["vote_average.gte"] == tmdb.KEYWORD_MIN_RATING for p in keyword_steps)
        assert plain_steps[0]["vote_average.gte"] == 6.0

    @pytest.mark.asyncio
    async def test_gems_must_be_at_least_a_year_old(self):
        from datetime import date, timedelta
        calls = []

        def discover(params):
            return {"results": [], "total_pages": 0}

        with patch("tmdb._get_client", return_value=_client_with(_router({}, discover, calls=calls))):
            await discover_movies({"genres": [27], "gem_mode": True}, page=1)

        gem = next(p for path, p in calls if "vote_count.lte" in p)
        cutoff = date.fromisoformat(gem["primary_release_date.lte"])
        assert date.today() - cutoff == timedelta(days=tmdb.GEM_MIN_AGE_DAYS)


def _films(ids):
    return [{"id": i, "title": f"Movie {i}"} for i in ids]


def _paged(ids):
    """Fake one TMDb query's ranking: serves `ids` 20 per page, like TMDb."""
    def page(n):
        return {"results": _films(ids[(n - 1) * 20: n * 20]), "total_results": len(ids)}
    return page


class TestRankedPaging:

    @pytest.mark.asyncio
    async def test_try_again_shows_the_next_batch_of_five(self):
        ranking = _paged(list(range(1, 101)))
        calls = []

        def discover(params):
            return ranking(params["page"])

        batches = {}
        for page in (1, 2, 4, 5):
            with patch("tmdb._get_client", return_value=_client_with(_router({}, discover, calls=calls))):
                batches[page] = [m["id"] for m in await discover_movies({"genres": [35]}, page=page)]

        assert batches[1] == [1, 2, 3, 4, 5]
        assert batches[2] == [6, 7, 8, 9, 10]
        assert batches[4] == [16, 17, 18, 19, 20]
        assert batches[5] == [21, 22, 23, 24, 25]      # crosses into TMDb page 2
        assert calls[-1][1]["page"] == 2

    @pytest.mark.asyncio
    async def test_precise_matches_first_then_broader_ones(self):
        keyword_step = _paged(list(range(1, 8)))         # 7 heist films
        genre_step = _paged(list(range(100, 160)))       # 60 crime-comedies

        def discover(params):
            return (keyword_step if "with_keywords" in params else genre_step)(params["page"])

        kw = {"heist": (10051, "heist")}
        pages = []
        for page in (1, 2, 3):
            with patch("tmdb._get_client", return_value=_client_with(_router(kw, discover))):
                pages.append([m["id"] for m in
                              await discover_movies({"genres": [80], "keywords": ["heist"]}, page=page)])

        assert pages[0] == [1, 2, 3, 4, 5]
        assert pages[1] == [6, 7, 100, 101, 102]          # heist films run out, genre films top up
        assert pages[2] == [103, 104, 105, 106, 107]      # no repeats

    @pytest.mark.asyncio
    async def test_past_the_end_wraps_round(self):
        every = _paged(list(range(1, 9)))                 # only 8 films anywhere

        def discover(params):
            if params.get("vote_count.gte") == tmdb.RELAXED_MIN_VOTES:
                return {"results": [], "total_results": 0}
            return every(params["page"])

        with patch("tmdb._get_client", return_value=_client_with(_router({}, discover))):
            results = await discover_movies({"genres": [35]}, filters={"min_year": 2015}, page=3)

        assert [m["id"] for m in results] == [3, 4, 5, 6, 7]  # start 10 wraps to 10 % 8 = 2

    @pytest.mark.asyncio
    async def test_tiny_result_set_never_comes_back_empty(self):
        def discover(params):
            if params.get("vote_count.gte") == tmdb.RELAXED_MIN_VOTES:
                return {"results": [], "total_results": 0}
            return _paged([1, 2, 3])(params["page"])

        for page in (1, 2, 7):
            with patch("tmdb._get_client", return_value=_client_with(_router({}, discover))):
                results = await discover_movies({"genres": [35]}, page=page)
            assert sorted(m["id"] for m in results) == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_gem_slot_shows_a_different_gem_each_try(self):
        gems = _paged([900, 901, 902])

        def discover(params):
            if "vote_count.lte" in params:
                return gems(params["page"])
            return _paged(list(range(1, 101)))(params["page"])

        last = []
        for page in (1, 2, 3, 4):
            with patch("tmdb._get_client", return_value=_client_with(_router({}, discover))):
                last.append((await discover_movies({"genres": [53]}, page=page, gem_slot=True))[-1]["id"])

        assert last == [900, 901, 902, 900]               # one gem per page, then round again

    @pytest.mark.asyncio
    async def test_random_start_is_one_of_the_first_batches(self):
        starts = set()

        def discover(params):
            return _paged(list(range(1, 101)))(params["page"])

        for _ in range(60):
            with patch("tmdb._get_client", return_value=_client_with(_router({}, discover))):
                starts.add((await discover_movies({"genres": [35]}))[0]["id"])

        assert starts <= {1, 6, 11} and len(starts) >= 2

    @pytest.mark.asyncio
    async def test_huge_page_numbers_cycle(self, captured_query):
        queries, mock_get = captured_query
        with patch("tmdb._get_client", return_value=_client_with(mock_get)):
            await discover_movies({"genres": [35]}, page=tmdb.MAX_PAGE + 1)
        assert queries[0]["params"]["page"] == 1

    @pytest.mark.asyncio
    async def test_overlapping_steps_never_show_a_film_twice(self):
        # Realistic: the broader search contains the precise one's films too
        heist = list(range(1, 8))
        crime_comedy = [x for pair in zip(heist, range(100, 107)) for x in pair] + list(range(107, 160))
        kw_step, genre_step = _paged(heist), _paged(crime_comedy)

        def discover(params):
            return (kw_step if "with_keywords" in params else genre_step)(params["page"])

        kw = {"heist": (10051, "heist")}
        shown = []
        for page in (1, 2, 3, 4):
            with patch("tmdb._get_client", return_value=_client_with(_router(kw, discover))):
                shown += [m["id"] for m in
                          await discover_movies({"genres": [80], "keywords": ["heist"]}, page=page)]

        assert len(shown) == len(set(shown)) == 20
        assert shown[:7] == heist                          # precise matches first

    @pytest.mark.asyncio
    async def test_gem_slot_pages_move_on_by_four(self):
        def discover(params):
            if "vote_count.lte" in params:
                return _paged([900, 901, 902])(params["page"])
            return _paged(list(range(1, 101)))(params["page"])

        picks = []
        for page in (1, 2):
            with patch("tmdb._get_client", return_value=_client_with(_router({}, discover))):
                picks.append([m["id"] for m in
                              await discover_movies({"genres": [53]}, page=page, gem_slot=True)][:4])

        assert picks == [[1, 2, 3, 4], [5, 6, 7, 8]]       # nothing skipped between pages

    @pytest.mark.asyncio
    async def test_deep_pages_jump_instead_of_walking(self):
        calls = []

        def discover(params):
            return _paged(list(range(1, 201)))(params["page"])

        with patch("tmdb._get_client", return_value=_client_with(_router({}, discover, calls=calls))):
            results = await discover_movies({"genres": [35]}, page=20)

        assert [m["id"] for m in results] == [96, 97, 98, 99, 100]
        assert [p["page"] for _, p in calls] == [5]        # straight to TMDb page 5

    @pytest.mark.asyncio
    async def test_gem_quality_films_only_appear_in_the_gem_slot(self):
        old = "2010-01-01"
        def film(i, votes, rating, genres=(53,), released=old):
            return {"id": i, "title": f"M{i}", "vote_count": votes, "vote_average": rating,
                    "genre_ids": list(genres), "release_date": released}

        standard = [
            film(1, 20000, 8.5), film(2, 900, 8.1),            # 2 is gem quality
            film(3, 15000, 8.0), film(4, 1200, 7.9),           # 4 is gem quality
            film(5, 9000, 7.8), film(6, 2500, 7.4),            # 6 rated below the gem bar
            film(7, 800, 7.7, genres=(18,)),                   # not in the gem genre
            film(8, 700, 7.6, released="2099-01-01"),          # too new to be a gem
        ] + [film(i, 5000, 7.0) for i in range(9, 40)]
        gems = [m for m in standard if m["id"] in (2, 4)]

        def discover(params):
            ranking = gems if "vote_count.lte" in params else standard
            return _paged(ranking)(params["page"]) | {"results": ranking[(params["page"] - 1) * 20:][:20]}

        pages = []
        for page in (1, 2, 3):
            with patch("tmdb._get_client", return_value=_client_with(_router({}, discover))):
                pages.append(await discover_movies({"genres": [53]}, page=page, gem_slot=True))

        picks = [m["id"] for p in pages for m in p if not m["is_gem"]]
        gem_ids = [m["id"] for p in pages for m in p if m["is_gem"]]
        assert picks[:6] == [1, 3, 5, 6, 7, 8]
        assert not set(picks) & {2, 4}                     # never shown as ordinary picks
        assert gem_ids == [2, 4, 2]                        # one gem per page, then round again
