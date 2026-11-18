"""Grok Build 订阅鉴权：复用 `grok login` 写入的 ~/.grok/auth.json。

``BEN_MODEL=grok`` 或 ``grok/<model>`` 时，请求打到
``https://cli-chat-proxy.grok.com/v1``，Bearer 为 auth.x.ai OAuth access
token（不是 ``xai-`` API key，也不可用在 ``api.x.ai``）。接近过期时就地刷新，
其余 CLI 记录字段不动。

``xai/grok-*`` 仍走 API key 路由，本模块不管。

Cursor 账号须为 Privacy Mode (no training)；Legacy (no storage) 会被代理拒绝。
"""
from __future__ import annotations

import contextlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

PROXY_BASE_URL = os.environ.get(
    "GROK_CLI_CHAT_PROXY_BASE_URL", "https://cli-chat-proxy.grok.com/v1"
)
TOKEN_URL = "https://auth.x.ai/oauth2/token"  # noqa: S105
DEFAULT_MODEL = "grok-4.6"
SUBSCRIPTION_PREFIX = "grok/"

_TOKEN_TIMEOUT = 30
_EXPIRY_SKEW_S = 300
_DEFAULT_TTL_S = 6 * 60 * 60

AUTH_PATH = Path.home() / ".grok" / "auth.json"
VERSION_PATH = Path.home() / ".grok" / "version.json"
_FALLBACK_CLIENT_VERSION = "1.0.77"
_SECRET_MODE = 0o600

_refresh_lock = threading.Lock()


class GrokBuildAuthError(Exception):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


class GrokBuildPrivacyError(Exception):
    def __init__(self, model: str, original: BaseException | None = None) -> None:
        self.model = model
        self.original = original
        super().__init__(
            f"'{model}' was refused because this Cursor account is in Legacy (no storage). "
            "Open Cursor Settings → Privacy → Privacy Mode (no training). "
            "Grok Build cannot run until that setting is saved."
        )


_PRIVACY_MARKERS = (
    "privacy-mode:legacy",
    "legacy (no storage)",
    "not supported in legacy",
)


def is_privacy_mode_error(exc: BaseException) -> bool:
    if isinstance(exc, GrokBuildPrivacyError):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _PRIVACY_MARKERS)


def subscription_model(model_name: str | None) -> str | None:
    """``grok`` / ``grok/<model>`` → 实际 slug；其它返回 None。

    ``xai/grok-*`` 走 API key，不在此处理。
    """
    name = (model_name or "").strip()
    if name.lower() == "grok":
        return DEFAULT_MODEL
    if not name.lower().startswith(SUBSCRIPTION_PREFIX):
        return None
    return name[len(SUBSCRIPTION_PREFIX):] or None


def skips_api_key(model_name: str | None) -> bool:
    return subscription_model(model_name) is not None


def _read_store() -> dict[str, Any]:
    try:
        data = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_store(data: dict[str, Any]) -> None:
    AUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = AUTH_PATH.with_suffix(AUTH_PATH.suffix + ".tmp")
    with contextlib.suppress(FileNotFoundError):
        tmp.unlink()
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _SECRET_MODE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2) + "\n")
        tmp.replace(AUTH_PATH)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def read_record() -> dict[str, Any] | None:
    selected = _select_record(_read_store())
    if selected is None:
        return None
    _key, record = selected
    return record


def is_authenticated() -> bool:
    return read_record() is not None


def _select_record(store: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    for key, value in store.items():
        if not isinstance(value, dict):
            continue
        if not (value.get("key") and value.get("refresh_token")):
            continue
        issuer = str(value.get("oidc_issuer") or "")
        if issuer.startswith("https://auth.x.ai") or str(key).startswith("https://auth.x.ai"):
            return str(key), value
    return None


def _parse_expiry(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    if "." in text:
        head, frac = text.split(".", 1)
        digits: list[str] = []
        rest = ""
        for index, char in enumerate(frac):
            if char.isdigit():
                digits.append(char)
            else:
                rest = frac[index:]
                break
        trimmed = "".join(digits[:6])
        text = f"{head}.{trimmed}{rest}" if trimmed else f"{head}{rest}"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _near_expiry(record: dict[str, Any]) -> bool:
    expires_at = _parse_expiry(record.get("expires_at"))
    if expires_at is None:
        return True
    return expires_at - _EXPIRY_SKEW_S <= time.time()


def _format_expiry(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@contextlib.contextmanager
def _refresh_guard() -> Iterator[None]:
    with _refresh_lock:
        try:
            import fcntl

            lock_path = AUTH_PATH.with_name(AUTH_PATH.name + ".ben.lock")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = lock_path.open("a")
        except (ImportError, OSError):
            yield
            return
        try:
            with contextlib.suppress(OSError):
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


def refresh_tokens(record: dict[str, Any]) -> dict[str, Any]:
    client_id = record.get("oidc_client_id")
    refresh = record.get("refresh_token")
    if (
        not isinstance(client_id, str)
        or not client_id
        or not isinstance(refresh, str)
        or not refresh
    ):
        raise GrokBuildAuthError(
            "not_authenticated", "Grok login is missing a refresh token; run: grok login"
        )
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": client_id,
    }).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TOKEN_TIMEOUT) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8", errors="replace")
            status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        raise GrokBuildAuthError(
            "refresh_failed",
            "Grok login could not be refreshed. Run `grok login` and re-run.",
        ) from exc
    except urllib.error.URLError as exc:
        raise GrokBuildAuthError(
            "refresh_failed", "could not reach auth.x.ai to refresh the Grok login"
        ) from exc
    if status != 200:
        raise GrokBuildAuthError(
            "refresh_failed",
            "Grok login could not be refreshed. Run `grok login` and re-run.",
        )
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise GrokBuildAuthError(
            "refresh_failed", "auth.x.ai returned a non-JSON token response"
        ) from exc
    access = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(access, str) or not access:
        raise GrokBuildAuthError("refresh_failed", "auth.x.ai did not return an access token")
    updated = dict(record)
    updated["key"] = access
    new_refresh = payload.get("refresh_token") if isinstance(payload, dict) else None
    if isinstance(new_refresh, str) and new_refresh:
        updated["refresh_token"] = new_refresh
    expires_in = payload.get("expires_in") if isinstance(payload, dict) else None
    try:
        ttl = int(expires_in)
    except (TypeError, ValueError):
        ttl = _DEFAULT_TTL_S
    updated["expires_at"] = _format_expiry(time.time() + max(ttl, 1))
    return updated


def get_valid_token() -> str:
    record = read_record()
    if record is None:
        raise GrokBuildAuthError("not_authenticated", "not signed in to Grok; run: grok login")
    if not _near_expiry(record):
        return str(record["key"])
    with _refresh_guard():
        store = _read_store()
        selected = _select_record(store)
        if selected is None:
            raise GrokBuildAuthError("not_authenticated", "not signed in to Grok; run: grok login")
        store_key, record = selected
        if not _near_expiry(record):
            return str(record["key"])
        try:
            refreshed = refresh_tokens(record)
        except GrokBuildAuthError:
            latest = _select_record(_read_store())
            if (
                latest
                and latest[1].get("refresh_token") != record.get("refresh_token")
                and not _near_expiry(latest[1])
            ):
                return str(latest[1]["key"])
            raise
        store[store_key] = refreshed
        _write_store(store)
        return str(refreshed["key"])


def client_version() -> str:
    try:
        data = json.loads(VERSION_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _FALLBACK_CLIENT_VERSION
    version = data.get("version") if isinstance(data, dict) else None
    if isinstance(version, str) and version.strip():
        return version.strip()
    return _FALLBACK_CLIENT_VERSION


def client_headers() -> dict[str, str]:
    version = client_version()
    return {
        "User-Agent": f"grok-cli/{version}",
        "x-grok-client-version": version,
        "x-grok-client-identifier": "grok-cli",
    }


def build_openai_client():
    """同步 OpenAI 客户端；每次请求前刷新 Bearer。"""
    from openai import OpenAI

    get_valid_token()
    headers = client_headers()
    try:
        import httpx
    except ImportError:
        return OpenAI(
            api_key=get_valid_token(),
            base_url=PROXY_BASE_URL,
            default_headers=headers,
            max_retries=0,
        )

    def _auth_hook(request: Any) -> None:
        request.headers["Authorization"] = f"Bearer {get_valid_token()}"
        for name, value in client_headers().items():
            request.headers[name] = value

    http_client = httpx.Client(
        timeout=httpx.Timeout(600.0, connect=30.0),
        event_hooks={"request": [_auth_hook]},
    )
    return OpenAI(
        api_key="ben-grok-build",
        base_url=PROXY_BASE_URL,
        default_headers=headers,
        http_client=http_client,
        max_retries=0,
    )
