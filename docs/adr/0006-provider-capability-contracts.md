# ADR 0006: Provider capability contracts

**Status:** Accepted and implemented in M3

## Context

The five locked providers use materially different transport and action paths: adaptive polling, signed webhooks, OAuth-backed polling, checkpointed synchronization, and playback commands. A single provider interface would force unrelated responsibilities onto every integration and would blur vendor DTOs into shared application contracts.

## Decision

Use small structural protocols for `PollSource`, `WebhookSource`, `CommandTarget`, and health reporting. Provider packages may implement one or more capabilities and register them explicitly. Use a typed immutable `Observation[ContentModel]` as the provider-neutral boundary before change detection/domain normalization and the existing canonical-event path. Keep vendor DTOs and OAuth mechanics within each provider package. The current registry is a small in-process capability map, not a plugin loader.

Do not define a reusable OAuth protocol yet. Spotify and Google share OAuth vocabulary but differ in scopes, account lifecycle, refresh behavior, and application semantics; a common interface should follow evidence from their implementations. Both will use the shared encrypted connection storage.

## Consequences

- Provider branches can add their adapters without changing canonical events or the M1 outbox/projector path.
- Poll and webhook delivery remain separate capabilities; reconciliation can coexist with webhooks.
- Observations remain adapter input, not domain/frontend contracts. Meaningful changes normalize to canonical events and enter the transactional event/outbox path.
- Capability registration and health state are single-process in P0. No multi-instance guarantee is added.
- The five M3 provider packages register only their required capabilities. M3 adds no provider-specific UI.
