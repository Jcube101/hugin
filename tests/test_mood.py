import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from mood import _parse_response, interpret_mood, interpret_group_mood, GENRE_NAME_TO_ID


def _mock_claude_response(text):
    """Create a mock Anthropic response object."""
    response = MagicMock()
    response.content = [MagicMock(text=text)]
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

    def test_sort_by_with_asc_suffix_preserved(self):
        raw = json.dumps({
            "genres": [35],
            "keywords": [],
            "vote_floor": 7.0,
            "gem_mode": False,
            "sort_by": "vote_average.asc",
        })
        result = _parse_response(raw)
        assert result["sort_by"] == "vote_average.asc"

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
        assert "sort_by" not in result or result.get("sort_by") is None

    def test_missing_gem_mode(self):
        raw = json.dumps({
            "genres": [35],
            "keywords": ["funny"],
            "vote_floor": 6.5,
            "sort_by": "popularity.desc",
        })
        result = _parse_response(raw)
        assert result.get("gem_mode") is None


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
