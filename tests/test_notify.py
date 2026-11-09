import json
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest

import notify
from password import get_today_password

TEST_URL = "https://n8n.invalid/webhook/hugin-word-test"
NOON = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def _at(moment):
    return patch("notify._now", return_value=moment)


def _client_answering(handler):
    """Patch notify's client so requests go to `handler` instead of the network."""
    return patch(
        "notify._make_client",
        side_effect=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


class TestReserveSend:

    def test_first_tap_sends(self):
        with _at(NOON):
            assert notify.reserve_send() is True

    def test_second_tap_within_cooldown_skipped(self):
        with _at(NOON):
            assert notify.reserve_send() is True
        with _at(NOON + timedelta(minutes=1)):
            assert notify.reserve_send() is False

    def test_tap_after_cooldown_sends(self):
        with _at(NOON):
            notify.reserve_send()
        with _at(NOON + notify.COOLDOWN):
            assert notify.reserve_send() is True

    def test_daily_limit(self):
        moment = NOON
        for _ in range(notify.DAILY_LIMIT):
            with _at(moment):
                assert notify.reserve_send() is True
            moment += notify.COOLDOWN
        with _at(moment):
            assert notify.reserve_send() is False

    def test_limit_resets_at_utc_midnight(self):
        notify._state.update(date="2026-11-09", count=notify.DAILY_LIMIT)
        with _at(datetime(2026, 11, 10, 0, 1, tzinfo=timezone.utc)):
            assert notify.reserve_send() is True

    def test_no_webhook_configured_sends_nothing(self, monkeypatch, caplog):
        monkeypatch.delenv("HUGIN_WORD_WEBHOOK_URL")
        with caplog.at_level(logging.WARNING, logger="hugin.notify"):
            assert notify.reserve_send() is False
        assert "HUGIN_WORD_WEBHOOK_URL" in caplog.text


class TestSendTodayWord:

    @pytest.mark.asyncio
    async def test_posts_only_todays_word(self):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200)

        with _client_answering(handler):
            assert await notify.send_today_word() is True
        assert len(seen) == 1
        assert str(seen[0].url) == TEST_URL
        assert seen[0].method == "POST"
        assert json.loads(seen[0].content) == {"word": get_today_password()}

    @pytest.mark.asyncio
    async def test_error_status_frees_the_cooldown(self):
        with _at(NOON):
            notify.reserve_send()
        with _client_answering(lambda request: httpx.Response(500)):
            assert await notify.send_today_word() is False
        # Job can tap again straight away instead of waiting out the cooldown
        with _at(NOON + timedelta(seconds=10)):
            assert notify.reserve_send() is True

    @pytest.mark.asyncio
    async def test_network_error_never_raises(self):
        def handler(request):
            raise httpx.ConnectError("connection refused", request=request)

        with _client_answering(handler):
            assert await notify.send_today_word() is False

    @pytest.mark.asyncio
    async def test_webhook_url_and_word_never_logged(self, caplog):
        def handler(request):
            raise httpx.ConnectError(f"failed to reach {request.url}", request=request)

        with caplog.at_level(logging.INFO, logger="hugin.notify"), \
             _client_answering(handler):
            await notify.send_today_word()
        with caplog.at_level(logging.INFO, logger="hugin.notify"), \
             _client_answering(lambda request: httpx.Response(200)):
            await notify.send_today_word()
        assert "ConnectError" in caplog.text
        assert "hugin-word-test" not in caplog.text
        assert get_today_password() not in caplog.text
