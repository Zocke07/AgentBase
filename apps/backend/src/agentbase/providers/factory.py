"""Construct providers from settings in one implementation-selection point."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from agentbase.providers.anthropic import AnthropicProvider
from agentbase.providers.base import Provider, ProviderAuthError
from agentbase.providers.chatgpt import (
    ChatGPTInferenceRuntime,
    ChatGPTSubscriptionProvider,
)
from agentbase.providers.ollama import MODEL_PREFIX as OLLAMA_MODEL_PREFIX
from agentbase.providers.ollama import OllamaProvider
from agentbase.providers.openai import OpenAIProvider

if TYPE_CHECKING:
    import httpx2

    from agentbase.secrets import SecretStore
    from agentbase.store.settings import WorkspaceSettings

__all__ = [
    "SUPPORTED_PROVIDERS",
    "UnknownProviderError",
    "build_provider",
    "qualified_model",
]

#: Provider-to-required-secret map; ``None`` needs no secret.
SUPPORTED_PROVIDERS: Final[dict[str, str | None]] = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "ollama": None,
}


class UnknownProviderError(LookupError):
    """Provider name has no implementation."""

    def __init__(self, provider: str) -> None:
        supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
        super().__init__(
            f"unknown provider {provider!r}. Supported providers are: {supported}."
        )
        self.provider = provider


def qualified_model(provider: str, model: str) -> str:
    """Return ledger model ID, not raw user input.

    Prefix Ollama with ``ollama/``; price checks must use this identifier.
    Raw names previously made every Ollama run look unpriced.
    """
    if provider == "ollama" and not model.startswith(OLLAMA_MODEL_PREFIX):
        return OLLAMA_MODEL_PREFIX + model
    return model


#: User-facing provider names.
_PROVIDER_NAMES: Final[dict[str, str]] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "ollama": "Ollama",
}


def build_provider(
    settings: WorkspaceSettings,
    secrets: SecretStore,
    client: httpx2.AsyncClient | None = None,
    chatgpt_runtime: ChatGPTInferenceRuntime | None = None,
) -> Provider:
    """Build provider named in ``settings``.

    :raises UnknownProviderError: for unrecognized provider name.
    :raises ProviderAuthError: when required key did not arrive; raise early to
        name credential rather than return a later 401.
    """
    name = settings.provider

    if name not in SUPPORTED_PROVIDERS:
        raise UnknownProviderError(name)

    if name == "openai" and settings.openai_access == "chatgpt":
        if chatgpt_runtime is None:
            raise ProviderAuthError(
                "ChatGPT subscription access is unavailable in this process."
            )
        return ChatGPTSubscriptionProvider(chatgpt_runtime, settings.model)

    required_secret = SUPPORTED_PROVIDERS[name]
    api_key = ""
    if required_secret is not None:
        stored = secrets.get(required_secret)
        if not stored:
            # Explain action, location, and required restart without keychain jargon.
            shown = _PROVIDER_NAMES.get(name, name)
            msg = (
                f"No API key for {shown} yet. Add one in Settings under Keys, then "
                f"restart AgentBase when it offers to: the key is read at startup."
            )
            raise ProviderAuthError(msg)
        api_key = stored

    if name == "anthropic":
        return AnthropicProvider(api_key=api_key, model=settings.model, client=client)

    if name == "openai":
        return OpenAIProvider(api_key=api_key, model=settings.model, client=client)

    return OllamaProvider(
        model=settings.model,
        base_url=settings.ollama_base_url,
        client=client,
    )
