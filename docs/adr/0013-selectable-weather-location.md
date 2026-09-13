# ADR 0013: Persist the user's weather location

## Status

Accepted

## Context

Weather originally used fixed latitude, longitude, and timezone environment values. That made the selected physical place an operator setting and led the UI to derive a visible city name from an IANA timezone. A personal command center needs place search, a user-controlled active location, durable selection across restarts, and location-specific atmosphere without changing the existing weather event path.

## Decision

Use Open-Meteo geocoding for bounded, debounced place search. Normalize its response into a provider-independent `WeatherLocation`, persist the selected record and the five most recent places in PostgreSQL, and have the existing scheduled weather source read the current selection for every observation. The location-selection API commits selection before requesting an immediate poll through the shared scheduler. Weather cache and comparison checkpoints are scoped to location identity, so a location switch does not compare unrelated conditions or emit a browsing-only timeline event.

Keep the dashboard clock system-local. Use the selected location's IANA timezone only to compute the background's local time phase. Use observed provider condition categories for weather treatment. The UI obtains its physical place label from geocoding and never infers it from timezone text.

Existing coordinate/timezone environment settings remain a first-run bootstrap fallback. If configured without a saved selection, resolve the coordinates to a human-readable place using a one-time, serialized OpenStreetMap Nominatim reverse lookup. This fallback is not used for interactive search. When no location exists, leave weather unconfigured and prompt the user to select one; do not invent a coordinate, city, or condition.

## Consequences

- PostgreSQL is authoritative for selection and recents; browser state is a view cache only.
- A new Alembic migration adds the shared location and singleton-selection tables.
- Switching places requires no environment edit or process restart and requests a forecast immediately.
- The existing canonical-event, outbox, projector, timeline, and health contracts remain in use.
- Public reverse-geocoding is limited to legacy coordinate bootstrap and follows a one-request-per-second bound; normal search and selection use Open-Meteo.
- The system clock does not move when browsing another timezone; only the atmospheric scene uses selected-place local time.
