import hashlib
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from password import WORD_LIST, get_today_password, is_valid_password


def _fixed_date(date_str, fmt="%Y-%m-%d"):
    """Return a patcher that freezes password.datetime.now to return the given date."""
    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.strptime(date_str, fmt).replace(tzinfo=tz)
    return patch("password.datetime", FakeDateTime)


def _fixed_time(datetime_str):
    return _fixed_date(datetime_str, "%Y-%m-%d %H:%M")


def _word_on(date_str, seed="test"):
    raw = hashlib.sha256(f"{seed}{date_str}".encode()).digest()
    return WORD_LIST[int.from_bytes(raw[:4], "big") % len(WORD_LIST)]


class TestGetTodayPassword:

    def test_known_seed_and_date(self):
        seed = "known-test-seed"
        date_str = "2026-05-07"
        raw = hashlib.sha256(f"{seed}{date_str}".encode()).digest()
        idx = int.from_bytes(raw[:4], "big") % len(WORD_LIST)
        expected = WORD_LIST[idx]

        with _fixed_date(date_str), patch.dict("os.environ", {"HUGIN_SEED": seed}):
            assert get_today_password() == expected

    def test_always_returns_word_from_list(self):
        with patch.dict("os.environ", {"HUGIN_SEED": "test-seed"}):
            for day in range(1, 31):
                date_str = f"2026-01-{day:02d}"
                with _fixed_date(date_str):
                    assert get_today_password() in WORD_LIST

    def test_different_dates_give_different_words(self):
        words = set()
        with patch.dict("os.environ", {"HUGIN_SEED": "test-seed"}):
            for day in range(1, 31):
                date_str = f"2026-01-{day:02d}"
                with _fixed_date(date_str):
                    words.add(get_today_password())
        assert len(words) >= 10

    def test_same_date_always_same_word(self):
        with _fixed_date("2026-03-15"), patch.dict("os.environ", {"HUGIN_SEED": "stable"}):
            first = get_today_password()
            second = get_today_password()
        assert first == second

    def test_seed_change_changes_output(self):
        with _fixed_date("2026-03-15"):
            with patch.dict("os.environ", {"HUGIN_SEED": "seed-a"}):
                word_a = get_today_password()
            with patch.dict("os.environ", {"HUGIN_SEED": "seed-b"}):
                word_b = get_today_password()
        assert word_a != word_b

    def test_empty_seed_raises(self):
        # The old silent "default-seed" fallback produced a wrong, guessable word
        with _fixed_date("2026-03-15"), patch.dict("os.environ", {"HUGIN_SEED": ""}):
            with pytest.raises(RuntimeError, match="HUGIN_SEED"):
                get_today_password()

    def test_missing_seed_raises(self):
        with _fixed_date("2026-03-15"), patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="HUGIN_SEED"):
                get_today_password()


class TestIsValidPassword:

    def test_todays_word_is_valid(self):
        with _fixed_time("2026-03-15 18:00"), patch.dict("os.environ", {"HUGIN_SEED": "test"}):
            assert is_valid_password(_word_on("2026-03-15")) is True

    @pytest.mark.parametrize("variant", ["{w}", "{W}", " {w} ", "{C}"])
    def test_case_and_spaces_ignored(self, variant):
        word = _word_on("2026-03-15")
        typed = variant.format(w=word, W=word.upper(), C=word.capitalize())
        with _fixed_time("2026-03-15 18:00"), patch.dict("os.environ", {"HUGIN_SEED": "test"}):
            assert is_valid_password(typed) is True

    @pytest.mark.parametrize("guess", ["", None, "nope", "émber", "ember\x00", "a" * 100])
    def test_wrong_or_odd_input_is_invalid_without_crashing(self, guess):
        with _fixed_time("2026-03-15 18:00"), patch.dict("os.environ", {"HUGIN_SEED": "test"}):
            if guess == _word_on("2026-03-15"):
                pytest.skip("guess happens to be today's word")
            assert is_valid_password(guess) is False

    def test_yesterdays_word_accepted_just_after_midnight(self):
        with _fixed_time("2026-03-15 00:30"), patch.dict("os.environ", {"HUGIN_SEED": "test"}):
            assert is_valid_password(_word_on("2026-03-14")) is True

    def test_yesterdays_word_rejected_after_grace_period(self):
        today, yesterday = _word_on("2026-03-15"), _word_on("2026-03-14")
        if today == yesterday:
            pytest.skip("same word two days running")
        with _fixed_time("2026-03-15 01:30"), patch.dict("os.environ", {"HUGIN_SEED": "test"}):
            assert is_valid_password(yesterday) is False

    def test_seed_change_invalidates_word(self):
        word = _word_on("2026-03-15", seed="old-seed")
        if word == _word_on("2026-03-15", seed="new-seed"):
            pytest.skip("both seeds pick the same word")
        with _fixed_time("2026-03-15 18:00"), patch.dict("os.environ", {"HUGIN_SEED": "new-seed"}):
            assert is_valid_password(word) is False


