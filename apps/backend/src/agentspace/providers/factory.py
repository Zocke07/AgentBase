"""Construct a provider from settings: the one place that decides which class to instantiate."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from agentspace.providers.anthropic import AnthropicProvider
from agentspace.providers.base import Provider, ProviderAuthError
from agentspace.providers.ollama import MODEL_PREFIX as OLLAMA_MODEL_PREFIX
from agentspace.providers.ollama import OllamaProvider
from agentspace.providers.openai import OpenAIProvider

if TYPE_CHECKING:
    import httpx2

    from agentspace.secrets import SecretStore
    from agentspace.store.settings import WorkspaceSettings

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


def build_provider(
    settings: WorkspaceSettings,
    secrets: SecretStore,
    client: httpx2.AsyncClient | None = None,
) -> Provider:
    """Build the provider named in ``settings``.

    :raises UnknownProviderError: for an unrecognised provider name.
    :raises ProviderAuthError: when the provider needs a key and none arrived,
        raised here so the message names the credential rather than a 401 later.
    """
    name = settings.provider

    if name not in SUPPORTED_PROVIDERS:
        raise UnknownProviderError(name)

    required_secret = SUPPORTED_PROVIDERS[name]
    api_key = ""
    if required_secret is not None:
        stored = secrets.get(required_secret)
        if not stored:
            msg = (
                f"No API key for {name}. Add it in settings: it is read from the OS "
                f"keychain and passed to the sidecar at startup, so the app must be "
                f"restarted after adding one."
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
