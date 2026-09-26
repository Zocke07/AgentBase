"""Construct a provider from settings: the one place that decides which class to instantiate."""

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

#: Provider name to the secret it needs, or ``None`` for one that needs none.
SUPPORTED_PROVIDERS: Final[dict[str, str | None]] = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "ollama": None,
}


class UnknownProviderError(LookupError):
    """Raised for a provider name that has no implementation."""

    def __init__(self, provider: str) -> None:
        supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
        super().__init__(
            f"unknown provider {provider!r}. Supported providers are: {supported}."
        )
        self.provider = provider


def qualified_model(provider: str, model: str) -> str:
    """The model id as the ledger will see it, not as the user typed it.

    Ollama prefixes `ollama/`, and every question about a model's price has
    to be asked about this string. Asking about the raw value once told every
    Ollama user their runs would be refused.
    """
    if provider == "ollama" and not model.startswith(OLLAMA_MODEL_PREFIX):
        return OLLAMA_MODEL_PREFIX + model
    return model


#: How each provider is named to a person, in messages they read.
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
    """Build the provider named in ``settings``.

    :raises UnknownProviderError: for an unrecognised provider name.
    :raises ProviderAuthError: when the provider needs a key and none arrived,
        raised here so the message names the credential rather than a 401 later.
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
            # Read by people who have never heard of a keychain or a sidecar:
            # say what to do, where, and the one surprise (the restart).
            shown = _PROVIDER_NAMES.get(name, name)
            msg = (
                f"No API key for {shown} yet. Add one in Settings under Keys, then "
                f"restart AgentSpace when it offers to: the key is read at startup."
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
