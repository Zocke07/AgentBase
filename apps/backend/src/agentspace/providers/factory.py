"""Construct a provider from settings.

This module is the Phase 3 acceptance criterion in one function: "switching
provider is a settings change with no code change". Everything above it asks
for *a provider* and receives one; the decision of which class to instantiate
happens here and nowhere else.

The registry is a dict rather than a chain of ``if`` statements so that adding
a provider is a single entry, and so a test can assert the set of supported
names without importing each implementation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from agentspace.providers.anthropic import AnthropicProvider
from agentspace.providers.base import Provider, ProviderAuthError
from agentspace.providers.ollama import OllamaProvider
from agentspace.providers.openai import OpenAIProvider

if TYPE_CHECKING:
    import httpx2

    from agentspace.secrets import SecretStore
    from agentspace.store.settings import WorkspaceSettings

__all__ = ["SUPPORTED_PROVIDERS", "UnknownProviderError", "build_provider"]

#: Provider name to the secret it needs, or ``None`` for one that needs none.
#: Ollama's ``None`` is load-bearing: it is what proves the abstraction does
#: not assume cloud (§5 Phase 3, §7).
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


def build_provider(
    settings: WorkspaceSettings,
    secrets: SecretStore,
    client: httpx2.AsyncClient | None = None,
) -> Provider:
    """Build the provider named in ``settings``.

    :raises UnknownProviderError: for an unrecognised provider name.
    :raises ProviderAuthError: when the provider needs a key and none arrived
        over the stdin handshake. Raised here, before a request is built, so
        the message names the missing credential rather than surfacing later as
        an opaque 401 from the vendor.
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
                f"No API key for {name}. Add it in settings — it is read from the OS "
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
