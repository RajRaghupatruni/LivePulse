# ADR 0005: Deterministic backend-owned focus state

- **Status:** Accepted
- **Date:** 2026-09-12

## Context

LivePulse organizes a persistent command-center screen around attention. If every client implements priorities independently, the same match lifecycle can lead to inconsistent emphasis, and an AI model must not become authoritative product state.

## Decision

The backend domain layer produces a normalized `FocusState` with score, severity, reason, transient flag, expiry, source, subject, and Match Mode. M2 implements deterministic football priorities: goals and red cards briefly elevate attention; scheduled, live, halftime, full-time, and idle states provide persistent baselines. The frontend renders this contract and schedules an authoritative refresh when transient attention expires. New domains may add deterministic policy through explicit domain functions; M2 does not add a generic plugin system or AI-based focus.

## Consequences

- Match Mode and visual emphasis follow the same authoritative projection used by APIs.
- The rules are testable and repeatable, and transient events settle back to current lifecycle state.
- Future mail, CI, media, weather, or provider-health priorities remain unimplemented until their real sources and policies exist.
