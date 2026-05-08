import hashlib
from datetime import datetime, timezone
from unittest.mock import patch

from password import WORD_LIST, get_today_hash, get_today_password


def _fixed_date(date_str):
    """Return a patcher that freezes password.datetime.now to return the given date."""
    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
    return patch("password.datetime", FakeDateTime)


class TestGetTodayPassword:

    def test_known_seed_and_date(self):
        seed = "yearning"
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

    def test_empty_seed_does_not_crash(self):
        with _fixed_date("2026-03-15"), patch.dict("os.environ", {"HUGIN_SEED": ""}):
            result = get_today_password()
        assert result in WORD_LIST

    def test_default_seed_fallback(self):
        with _fixed_date("2026-03-15"), patch.dict("os.environ", {}, clear=True):
            result = get_today_password()
        assert result in WORD_LIST


class TestGetTodayHash:

    def test_returns_16_char_string(self):
        with _fixed_date("2026-03-15"), patch.dict("os.environ", {"HUGIN_SEED": "test"}):
            h = get_today_hash()
        assert isinstance(h, str)
        assert len(h) == 16
        int(h, 16)  # should parse as hex

    def test_different_dates_give_different_hashes(self):
        hashes = set()
        with patch.dict("os.environ", {"HUGIN_SEED": "test"}):
            for day in range(1, 11):
                with _fixed_date(f"2026-02-{day:02d}"):
                    hashes.add(get_today_hash())
        assert len(hashes) == 10

    def test_hash_is_deterministic(self):
        with _fixed_date("2026-04-01"), patch.dict("os.environ", {"HUGIN_SEED": "test"}):
            h1 = get_today_hash()
            h2 = get_today_hash()
        assert h1 == h2
