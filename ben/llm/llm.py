"""OpenAI-compatible client construction and chat.completions calls."""
from __future__ import annotations

import os
import sys
import time

from ben import config
from ben.core.errors import FGError
from ben.llm import grok_build
from ben.llm.keys import _is_quota_error, _load_key_pool, _rotate_key, _seed_key_from_pool


def _sdk_credentials() -> tuple[str, str, str]:
    # pool entry #0 becomes the primary key when none is set (then rotation
    # advances ring-wise from it)
    _seed_key_from_pool()
    api_key = (
        config.get("BEN_API_KEY")
        or config.get("OPENAI_API_KEY")
        or ""
    ).strip()
    api_base = (
        config.get("BEN_API_BASE")
        or config.get("OPENAI_BASE_URL")
        or ""
    ).strip()
    model = (config.get("BEN_MODEL") or "").strip()
    return api_key, api_base, model


def flash_configured() -> bool:
    """True when a dedicated flash (sub-model) gateway is fully set."""
    return bool(
        (config.get("BEN_FLASH_MODEL") or "").strip()
        and (config.get("BEN_FLASH_API_KEY") or "").strip()
        and (config.get("BEN_FLASH_API_BASE") or "").strip()
    )


def resolve_model_tier(explicit: str | None = None) -> str:
    """``main`` (commander / default) or ``flash`` (workers when configured).

    Workers spawned by ``ben fleet`` export ``BEN_WORKER``; those prefer flash
    when ``BEN_FLASH_*`` is complete. Explicit ``main``/``flash`` always wins.
    """
    if explicit in ("main", "flash"):
        return explicit
    if os.environ.get("BEN_WORKER") and flash_configured():
        return "flash"
    return "main"


def openai_available() -> bool:
    try:
        import openai  # noqa: F401
        return True
    except ImportError:
        return False


def sdk_ready() -> bool:
    """True when openai is importable and credentials exist.

    Grok Build (``BEN_MODEL=grok`` / ``grok/...``) needs ``grok login``,
    not an API key. Model validity for other providers is checked in
    ``client_for`` so ``auto`` can fall back to cli on default ``sonnet``.
    """
    if not openai_available():
        return False
    model = (config.get("BEN_MODEL") or "").strip()
    if grok_build.subscription_model(model):
        return grok_build.is_authenticated()
    api_key, _, _model = _sdk_credentials()
    return bool(api_key)


def client_for(model_hint: str | None = None, *, tier: str = "main"):
    """Build an OpenAI client. Returns (client, model, info). max_retries=0."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise FGError(
            "openai package not installed; run `bash scripts/install.sh --with-sdk` "
            "or `pip install 'openai>=1.40,<3'`"
        ) from exc
    if tier == "flash":
        return _client_for_flash(model_hint)
    api_key, api_base, env_model = _sdk_credentials()
    model = (model_hint or env_model or "").strip()
    slug = grok_build.subscription_model(model)
    if slug:
        if not grok_build.is_authenticated():
            raise FGError(
                "Grok Build needs a login session; run `grok login` "
                "(reads ~/.grok/auth.json). Do not put the OAuth token on api.x.ai."
            )
        try:
            client = grok_build.build_openai_client()
        except grok_build.GrokBuildAuthError as exc:
            raise FGError(str(exc)) from exc
        info = {
            "api_base": grok_build.PROXY_BASE_URL,
            "model": slug,
            "provider": "grok-build",
            "tier": "main",
        }
        return client, slug, info
    if not api_key:
        raise FGError(
            "sdk engine needs BEN_API_KEY or OPENAI_API_KEY "
            "(or an entry in BEN_KEY_POOL), or set BEN_MODEL=grok after "
            "`grok login`. Copy .env.example to .env to get started"
        )
    if not model or model == "sonnet":
        raise FGError(
            "sdk engine needs BEN_MODEL set to an OpenAI-compatible model id "
            "(e.g. grok, grok/grok-4.6, glm-5.3); default 'sonnet' is cli-only"
        )
    kwargs = {"api_key": api_key, "max_retries": 0}
    if api_base:
        kwargs["base_url"] = api_base
    client = OpenAI(**kwargs)
    info = {"api_base": api_base, "model": model, "tier": "main"}
    return client, model, info


def _client_for_flash(model_hint: str | None = None):
    from openai import OpenAI

    if not flash_configured():
        raise FGError(
            "flash tier needs BEN_FLASH_MODEL + BEN_FLASH_API_KEY + "
            "BEN_FLASH_API_BASE in .env"
        )
    model = (model_hint or config.get("BEN_FLASH_MODEL") or "").strip()
    api_key = (config.get("BEN_FLASH_API_KEY") or "").strip()
    api_base = (config.get("BEN_FLASH_API_BASE") or "").strip()
    client = OpenAI(api_key=api_key, base_url=api_base, max_retries=0)
    info = {
        "api_base": api_base,
        "model": model,
        "provider": "flash",
        "tier": "flash",
    }
    return client, model, info


def _retry_after_seconds(message: str, attempt: int) -> float:
    """Backoff for transient/rate-limit errors; honor 'after N seconds' when present."""
    import re

    lower = message.lower()
    m = re.search(r"after\s+(\d+)\s*second", lower)
    if m:
        return float(max(1, int(m.group(1))) + 1)
    if "429" in lower or "rate_limit" in lower or "rate limit" in lower:
        return float(min(60, 2 * (2 ** (attempt - 1))))
    if any(
        tok in lower
        for tok in (
            "connection error", "connecterror", "timed out", "timeout",
            "temporarily unavailable", "502", "503", "504", "tls",
        )
    ):
        return float(min(60, 3 * (2 ** (attempt - 1))))
    return float(min(120, 10 * (2 ** (attempt - 1))))


def call_model(messages, tools=None, *, timeout: float, model: str | None = None,
               temperature: float | None = None, tier: str | None = None):
    """One chat.completions.create with quota rotation + exponential backoff."""
    resolved_tier = resolve_model_tier(tier)
    pool_size = max(1, len(_load_key_pool()) or 1)
    attempts = 1 + max(0, config.get_int("BEN_RETRY_MODEL"))
    # At least 4 tries so 429 / connection flaps survive BEN_RETRY_MODEL=0.
    max_tries = max(attempts, pool_size, 4)
    last_error: Exception | None = None
    for attempt in range(1, max_tries + 1):
        client, resolved_model, info = client_for(model, tier=resolved_tier)
        kwargs = {
            "model": resolved_model,
            "messages": messages,
            "timeout": timeout,
        }
        if tools:
            kwargs["tools"] = tools
        if temperature is not None:
            kwargs["temperature"] = temperature
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if grok_build.is_privacy_mode_error(exc):
                raise FGError(str(grok_build.GrokBuildPrivacyError(
                    resolved_model, exc
                ))) from exc
            msg = str(exc)
            # Grok Build / flash: do not rotate the main API key pool.
            if info.get("provider") not in ("grok-build", "flash") and (
                _is_quota_error(msg) or "401" in msg or "429" in msg
            ):
                if _rotate_key(backend="sdk"):
                    sys.stderr.write(
                        f"[ben] sdk quota/auth (attempt {attempt}/{max_tries}); "
                        "key rotated — retrying\n"
                    )
                    continue
            if attempt < max_tries:
                backoff = _retry_after_seconds(msg, attempt)
                sys.stderr.write(
                    f"[ben] sdk call failed (attempt {attempt}/{max_tries}): "
                    f"{exc}; retrying in {backoff:.0f}s\n"
                )
                time.sleep(backoff)
                continue
            break
    raise FGError(f"sdk chat.completions failed: {last_error}")
