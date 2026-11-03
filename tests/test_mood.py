import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import mood
from mood import _parse_response, interpret_mood, interpret_group_mood, GENRE_NAME_TO_ID


def _mock_claude_response(text):
    """Create a mock Anthropic response object."""
    response = MagicMock()
    response.content = [MagicMock(type="text", text=text)]
    return response


class TestParseResponse:

    def test_clean_json_response(self):
        raw = json.dumps({
            "genres": [35, 18],
            "keywords": ["witty"],
            "vote_floor": 7.0,
            "gem_mode": False,
            "sort_by": "vote_average.desc",
        })
        result = _parse_response(raw)
        assert result["genres"] == [35, 18]
        assert result["keywords"] == ["witty"]
        assert result["vote_floor"] == 7.0
        assert result["gem_mode"] is False
        assert result["sort_by"] == "vote_average.desc"

    def test_json_wrapped_in_code_fence(self):
        raw = '```json\n{"genres": [35], "keywords": ["funny"], "vote_floor": 6.5, "gem_mode": false, "sort_by": "popularity.desc"}\n```'
        result = _parse_response(raw)
        assert result["genres"] == [35]
        assert result["sort_by"] == "popularity.desc"

    def test_code_fence_without_json_tag(self):
        raw = '```\n{"genres": [28], "keywords": ["action"], "vote_floor": 7.0, "gem_mode": false, "sort_by": "vote_average.desc"}\n```'
        result = _parse_response(raw)
        assert result["genres"] == [28]

    def test_genre_names_instead_of_ids(self):
        raw = json.dumps({
            "genres": ["Comedy", "Drama"],
            "keywords": ["witty"],
            "vote_floor": 7.0,
            "gem_mode": False,
            "sort_by": "vote_average.desc",
        })
        result = _parse_response(raw)
        assert result["genres"] == [35, 18]

    def test_mixed_genre_names_and_ids(self):
        raw = json.dumps({
            "genres": [28, "Comedy", "Unknown Genre"],
            "keywords": [],
            "vote_floor": 6.5,
            "gem_mode": False,
            "sort_by": "popularity.desc",
        })
        result = _parse_response(raw)
        assert 28 in result["genres"]
        assert 35 in result["genres"]
        assert "Unknown Genre" not in result["genres"]

    def test_sort_by_without_suffix(self):
        raw = json.dumps({
            "genres": [35],
            "keywords": [],
            "vote_floor": 7.0,
            "gem_mode": False,
            "sort_by": "vote_average",
        })
        result = _parse_response(raw)
        assert result["sort_by"] == "vote_average.desc"

    def test_sort_by_outside_allowed_values_uses_default(self):
        # Ascending rating would surface the worst films first
        raw = json.dumps({
            "genres": [35],
            "keywords": [],
            "vote_floor": 7.0,
            "gem_mode": False,
            "sort_by": "vote_average.asc",
        })
        result = _parse_response(raw)
        assert result["sort_by"] == "vote_average.desc"

    def test_empty_genres_list(self):
        raw = json.dumps({
            "genres": [],
            "keywords": ["dark comedy"],
            "vote_floor": 7.0,
            "gem_mode": False,
            "sort_by": "popularity.desc",
        })
        result = _parse_response(raw)
        assert result["genres"] == []

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_response("NOT JSON AT ALL")

    def test_missing_sort_by_field(self):
        raw = json.dumps({
            "genres": [35],
            "keywords": ["funny"],
            "vote_floor": 6.5,
            "gem_mode": False,
        })
        result = _parse_response(raw)
        assert result["sort_by"] == "vote_average.desc"

    def test_missing_gem_mode(self):
        raw = json.dumps({
            "genres": [35],
            "keywords": ["funny"],
            "vote_floor": 6.5,
            "sort_by": "popularity.desc",
        })
        result = _parse_response(raw)
        assert result["gem_mode"] is False


class TestOutputValidation:
    """Claude's reply is shaped by user text, so nothing in it is trusted."""

    def test_string_false_gem_mode_is_not_true(self):
        result = _parse_response('{"genres": [35], "gem_mode": "false"}')
        assert result["gem_mode"] is False

    def test_string_true_gem_mode_is_not_true(self):
        result = _parse_response('{"genres": [35], "gem_mode": "true"}')
        assert result["gem_mode"] is False

    def test_real_true_gem_mode_kept(self):
        result = _parse_response('{"genres": [35], "gem_mode": true}')
        assert result["gem_mode"] is True

    def test_unknown_keys_dropped(self):
        result = _parse_response('{"genres": [35], "essay": "injected text"}')
        assert set(result) == {"genres", "keywords", "vote_floor", "gem_mode", "sort_by"}

    @pytest.mark.parametrize("raw_floor, expected", [
        (9.9, 8.0), (2, 5.5), ("7.2", 7.2), ("abc", 6.5), (None, 6.5),
    ])
    def test_vote_floor_clamped(self, raw_floor, expected):
        result = _parse_response(json.dumps({"genres": [35], "vote_floor": raw_floor}))
        assert result["vote_floor"] == expected

    def test_nan_vote_floor_uses_default(self):
        result = _parse_response('{"genres": [35], "vote_floor": NaN}')
        assert result["vote_floor"] == 6.5

    def test_unknown_sort_by_uses_default(self):
        result = _parse_response('{"genres": [35], "sort_by": "revenue.desc"}')
        assert result["sort_by"] == "vote_average.desc"

    def test_genre_ids_not_in_tmdb_list_dropped(self):
        result = _parse_response('{"genres": [35, 99999, true, 35, 18]}')
        assert result["genres"] == [35, 18]

    def test_keywords_cleaned_and_capped(self):
        raw = json.dumps({"genres": [], "keywords": [" heist ", "", 5] + [f"k{i}" for i in range(10)]})
        result = _parse_response(raw)
        assert result["keywords"][0] == "heist"
        assert len(result["keywords"]) == 5

    def test_sentence_around_json_is_handled(self):
        result = _parse_response('Here you go:\n{"genres": [27], "sort_by": "popularity.desc"}\nEnjoy!')
        assert result["genres"] == [27]

    def test_non_object_json_raises(self):
        with pytest.raises(ValueError):
            _parse_response("[35, 18]")


class TestClaudeRequest:

    def test_client_has_short_timeout_and_one_retry(self):
        assert mood.client.timeout == 15.0
        assert mood.client.max_retries == 1

    @pytest.mark.asyncio
    async def test_requests_structured_output(self):
        with patch("mood.client.messages.create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _mock_claude_response('{"genres": [35]}')
            await interpret_mood("funny")

        fmt = mock_create.call_args.kwargs["output_config"]["format"]
        assert fmt["type"] == "json_schema"
        assert fmt["schema"]["additionalProperties"] is False

    @pytest.mark.asyncio
    async def test_reads_text_block_not_first_block(self):
        response = MagicMock()
        response.content = [MagicMock(type="thinking"), MagicMock(type="text", text='{"genres": [18]}')]
        with patch("mood.client.messages.create", new_callable=AsyncMock, return_value=response):
            result = await interpret_mood("sad")
        assert result["genres"] == [18]


class TestInterpretMood:

    @pytest.mark.asyncio
    async def test_clean_json_response(self):
        mock_text = json.dumps({
            "genres": [35, 18],
            "keywords": ["witty"],
            "vote_floor": 7.0,
            "gem_mode": False,
            "sort_by": "vote_average.desc",
        })
        with patch("mood.client.messages.create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _mock_claude_response(mock_text)
            result = await interpret_mood("something funny")

        assert result["genres"] == [35, 18]
        assert result["vote_floor"] == 7.0
        mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_code_fence_stripped(self):
        mock_text = '```json\n{"genres": [27], "keywords": ["scary"], "vote_floor": 6.0, "gem_mode": false, "sort_by": "popularity.desc"}\n```'
        with patch("mood.client.messages.create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _mock_claude_response(mock_text)
            result = await interpret_mood("something scary")

        assert result["genres"] == [27]

    @pytest.mark.asyncio
    async def test_genre_names_mapped_to_ids(self):
        mock_text = json.dumps({
            "genres": ["Comedy", "Drama"],
            "keywords": ["witty"],
            "vote_floor": 7.0,
            "gem_mode": False,
            "sort_by": "vote_average.desc",
        })
        with patch("mood.client.messages.create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _mock_claude_response(mock_text)
            result = await interpret_mood("feel good")

        assert result["genres"] == [35, 18]


class TestInterpretGroupMood:

    @pytest.mark.asyncio
    async def test_two_moods_combined(self):
        mock_text = json.dumps({
            "genres": [18, 10749],
            "keywords": ["emotional", "romance"],
            "vote_floor": 7.0,
            "gem_mode": False,
            "sort_by": "vote_average.desc",
        })
        with patch("mood.client.messages.create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _mock_claude_response(mock_text)
            result = await interpret_group_mood(["something sad", "something romantic"])

        assert result["genres"] == [18, 10749]
        call_args = mock_create.call_args
        content = call_args.kwargs["messages"][0]["content"]
        assert "Person 1" in content
        assert "Person 2" in content

    @pytest.mark.asyncio
    async def test_single_mood_in_group(self):
        mock_text = json.dumps({
            "genres": [35],
            "keywords": ["funny"],
            "vote_floor": 6.5,
            "gem_mode": False,
            "sort_by": "popularity.desc",
        })
        with patch("mood.client.messages.create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _mock_claude_response(mock_text)
            result = await interpret_group_mood(["something funny"])

        assert result["genres"] == [35]

    @pytest.mark.asyncio
    async def test_four_moods_in_group(self):
        mock_text = json.dumps({
            "genres": [18],
            "keywords": ["ensemble"],
            "vote_floor": 7.0,
            "gem_mode": False,
            "sort_by": "vote_average.desc",
        })
        with patch("mood.client.messages.create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _mock_claude_response(mock_text)
            result = await interpret_group_mood(["a", "b", "c", "d"])

        call_args = mock_create.call_args
        content = call_args.kwargs["messages"][0]["content"]
        assert "Person 4" in content


class TestModelChoice:

    @pytest.mark.asyncio
    async def test_uses_haiku_5_5_at_low_effort(self):
        with patch("mood.client.messages.create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _mock_claude_response('{"genres": [35]}')
            await interpret_mood("funny")

        kwargs = mock_create.call_args.kwargs
        assert kwargs["model"] == "claude-haiku-5-5"
        assert kwargs["output_config"]["effort"] == "low"
        assert kwargs["max_tokens"] >= 1024  # thinking counts toward max_tokens

    @pytest.mark.asyncio
    async def test_refusal_retries_once_on_haiku_4_5_without_effort(self):
        refusal = MagicMock(stop_reason="refusal", content=[])
        refusal.stop_details.category = "general_harms"
        ok = _mock_claude_response('{"genres": [53], "keywords": ["revenge"]}')
        with patch("mood.client.messages.create", new_callable=AsyncMock, side_effect=[refusal, ok]) as mock_create:
            result = await interpret_mood("a brutal revenge thriller")

        assert result["genres"] == [53]
        second = mock_create.call_args_list[1].kwargs
        assert second["model"] == "claude-haiku-4-5-20251001"
        assert "effort" not in second["output_config"]
        assert second["output_config"]["format"]["type"] == "json_schema"

    @pytest.mark.asyncio
    async def test_no_fallback_call_when_not_refused(self):
        with patch("mood.client.messages.create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _mock_claude_response('{"genres": [35]}')
            await interpret_mood("funny")
        assert mock_create.call_count == 1


class TestInterpretationCache:

    @pytest.mark.asyncio
    async def test_same_mood_reuses_interpretation(self):
        with patch("mood.client.messages.create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _mock_claude_response('{"genres": [80], "keywords": ["heist"]}')
            first = await interpret_mood("A clever heist movie")
            second = await interpret_mood("  a clever   HEIST movie ")
        assert first == second
        assert mock_create.call_count == 1

    @pytest.mark.asyncio
    async def test_different_moods_are_separate(self):
        with patch("mood.client.messages.create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _mock_claude_response('{"genres": [35]}')
            await interpret_mood("funny")
            await interpret_mood("sad")
            await interpret_group_mood(["funny"])
        assert mock_create.call_count == 3

    @pytest.mark.asyncio
    async def test_callers_cannot_change_the_cached_copy(self):
        with patch("mood.client.messages.create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _mock_claude_response('{"genres": [27], "gem_mode": true}')
            first = await interpret_mood("hidden gem horror")
            first["gem_mode"] = False          # discover_movies does this on gem fallback
            first["genres"].append(35)
            second = await interpret_mood("hidden gem horror")
        assert second["gem_mode"] is True
        assert second["genres"] == [27]

    @pytest.mark.asyncio
    async def test_failed_interpretation_is_not_cached(self):
        bad = _mock_claude_response("not json")
        good = _mock_claude_response('{"genres": [18]}')
        with patch("mood.client.messages.create", new_callable=AsyncMock, side_effect=[bad, good]):
            with pytest.raises(ValueError):
                await interpret_mood("sad")
            assert (await interpret_mood("sad"))["genres"] == [18]
