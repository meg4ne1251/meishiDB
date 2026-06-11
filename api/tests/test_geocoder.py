"""住所→座標ジオコーダ（自前 Nominatim 想定）。httpx をスタブ化して分岐を検証。"""

import pytest

from app.core.config import get_settings
from app.services import geocoder


class _FakeResponse:
    def __init__(self, payload, *, raise_exc=None):
        self._payload = payload
        self._raise_exc = raise_exc

    def raise_for_status(self):
        if self._raise_exc:
            raise self._raise_exc

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """httpx.AsyncClient の最小スタブ。get の戻り値を差し込める。"""

    response: _FakeResponse | None = None
    last_params: dict | None = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None, headers=None):
        type(self).last_params = params
        return self.response


@pytest.fixture
def enable_geocoder(monkeypatch):
    monkeypatch.setattr(get_settings(), "geocoder_url", "http://geocoder:8080")


def _patch_client(monkeypatch, response):
    _FakeAsyncClient.response = response
    monkeypatch.setattr(geocoder.httpx, "AsyncClient", _FakeAsyncClient)


def test_is_configured(monkeypatch):
    monkeypatch.setattr(get_settings(), "geocoder_url", "")
    assert geocoder.is_configured() is False
    monkeypatch.setattr(get_settings(), "geocoder_url", "http://x")
    assert geocoder.is_configured() is True


async def test_geocode_returns_none_when_not_configured(monkeypatch):
    monkeypatch.setattr(get_settings(), "geocoder_url", "")
    assert await geocoder.geocode("東京都港区") is None


async def test_geocode_empty_address(enable_geocoder):
    assert await geocoder.geocode("   ") is None


async def test_geocode_success(enable_geocoder, monkeypatch):
    _patch_client(
        monkeypatch, _FakeResponse([{"lat": "35.6586", "lon": "139.7454"}])
    )
    coords = await geocoder.geocode("東京タワー")
    assert coords == (35.6586, 139.7454)
    # countrycodes=jp が付く
    assert _FakeAsyncClient.last_params["countrycodes"] == "jp"


async def test_geocode_no_results(enable_geocoder, monkeypatch):
    _patch_client(monkeypatch, _FakeResponse([]))
    assert await geocoder.geocode("どこにもない住所") is None


async def test_geocode_out_of_range_rejected(enable_geocoder, monkeypatch):
    _patch_client(monkeypatch, _FakeResponse([{"lat": "999", "lon": "139.0"}]))
    assert await geocoder.geocode("壊れた座標") is None


async def test_geocode_http_error_returns_none(enable_geocoder, monkeypatch):
    _patch_client(
        monkeypatch, _FakeResponse(None, raise_exc=RuntimeError("500 Server Error"))
    )
    assert await geocoder.geocode("エラー") is None
