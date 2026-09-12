"""Explicit capability registries, kept small and single-process for P0."""

from app.providers.base import CommandTarget, PollSource, WebhookSource


class ProviderRegistry:
    def __init__(self) -> None:
        self._poll_sources: dict[str, PollSource] = {}
        self._webhook_sources: dict[str, WebhookSource] = {}
        self._command_targets: dict[str, CommandTarget] = {}

    @property
    def poll_sources(self) -> tuple[PollSource, ...]:
        return tuple(self._poll_sources.values())

    def register_poll_source(self, source: PollSource) -> None:
        self._register(self._poll_sources, source)

    def register_webhook_source(self, source: WebhookSource) -> None:
        self._register(self._webhook_sources, source)

    def register_command_target(self, target: CommandTarget) -> None:
        self._register(self._command_targets, target)

    def command_target(self, provider_id: str) -> CommandTarget | None:
        return self._command_targets.get(provider_id)

    def webhook_source(self, provider_id: str) -> WebhookSource | None:
        return self._webhook_sources.get(provider_id)

    @staticmethod
    def _register(registry: dict[str, object], capability: object) -> None:
        provider_id = getattr(capability, "provider_id", None)
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("provider capability must have a non-empty provider_id")
        if provider_id in registry:
            raise ValueError(f"provider capability already registered: {provider_id}")
        registry[provider_id] = capability
