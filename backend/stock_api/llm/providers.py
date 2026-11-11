"""Provider presets and resolution of the settings into one OpenAI-compatible endpoint."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse


class LLMConfigError(ValueError):
    """The LLM settings are incomplete or name an unknown provider."""


@dataclass(frozen=True)
class ProviderPreset:
    base_url: str
    needs_key: bool = True
    # Path the OpenAI-compatible API lives under, appended to a user-supplied base URL.
    api_path: str = ""
    placeholder_key: str = ""


PRESETS: dict[str, ProviderPreset] = {
    "ollama": ProviderPreset(
        base_url="http://localhost:11434", needs_key=False, api_path="/v1", placeholder_key="ollama"
    ),
    "groq": ProviderPreset(base_url="https://api.groq.com/openai/v1"),
    "gemini": ProviderPreset(base_url="https://generativelanguage.googleapis.com/v1beta/openai/"),
    "openai": ProviderPreset(base_url="https://api.openai.com/v1"),
    "openrouter": ProviderPreset(base_url="https://openrouter.ai/api/v1"),
    "anthropic": ProviderPreset(base_url="https://api.anthropic.com/v1/"),
    # Any other OpenAI-compatible server (vLLM, LM Studio, llama.cpp ...): LLM_API_BASE required.
    "custom": ProviderPreset(base_url="", needs_key=False, placeholder_key="not-needed"),
}

NGROK_SKIP_WARNING_HEADER = "ngrok-skip-browser-warning"


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    base_url: str
    api_key: str = field(repr=False)
    headers: dict[str, str] = field(default_factory=dict)
    price_input_per_mtok: float = 0.0
    price_output_per_mtok: float = 0.0

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model}"


def is_ngrok_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return "ngrok" in host


def _join_api_path(base_url: str, api_path: str) -> str:
    base = base_url.rstrip("/")
    if api_path and not base.endswith(api_path):
        base += api_path
    return base


def resolve_provider(
    provider: str,
    model: str,
    *,
    api_base: str = "",
    api_key: str = "",
    extra_headers: dict[str, str] | None = None,
    price_input_per_mtok: float = 0.0,
    price_output_per_mtok: float = 0.0,
) -> ProviderConfig:
    """Turn raw settings into a ready-to-use endpoint, or raise LLMConfigError."""
    name = provider.strip().lower()
    preset = PRESETS.get(name)
    if preset is None:
        known = ", ".join(sorted(PRESETS))
        raise LLMConfigError(f"Unknown LLM provider {provider!r}. Use one of: {known}.")
    if not model.strip():
        raise LLMConfigError(f"LLM model is not set for provider {name!r} (LLM_MODEL).")

    base = api_base.strip() or preset.base_url
    if not base:
        raise LLMConfigError(f"Provider {name!r} needs a base URL (LLM_API_BASE).")
    base = _join_api_path(base, preset.api_path)

    key = api_key.strip()
    if not key:
        if preset.needs_key:
            raise LLMConfigError(f"Provider {name!r} needs an API key (LLM_API_KEY).")
        key = preset.placeholder_key

    headers = dict(extra_headers or {})
    if is_ngrok_url(base):
        # Free ngrok endpoints answer with an HTML warning page unless this header is sent.
        headers.setdefault(NGROK_SKIP_WARNING_HEADER, "true")

    return ProviderConfig(
        provider=name,
        model=model.strip(),
        base_url=base,
        api_key=key,
        headers=headers,
        price_input_per_mtok=price_input_per_mtok,
        price_output_per_mtok=price_output_per_mtok,
    )
