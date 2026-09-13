# Weather provider

Weather uses the public Open-Meteo geocoding and `/v1/forecast` services. No API key is required. Provider DTOs, HTTP details, WMO normalization, and units stay inside this package. The normalized current-weather service is exposed at `GET /api/v1/providers/weather/current`; health is available at `GET /api/v1/providers/weather/health`.

## Location selection

The user searches by place name through `GET /api/v1/providers/weather/location/search?q=...`, then saves a normalized geocoder result with `POST /api/v1/providers/weather/location/select`. `GET /api/v1/providers/weather/location` returns the selected place and up to five recent places. Search terms are length-bounded in the API and debounced in the browser; the geocoder returns at most six results and caches repeated queries briefly.

The selected place and recents are stored in PostgreSQL. The weather poll source reads the selected record on each poll, and selection asks the shared scheduler to refresh immediately. Forecast cache and change-detection checkpoints are location-scoped; selecting another city therefore does not compare its weather to the previous city's conditions or create an event simply because the user browsed there. Meaningful condition changes continue through the canonical event and transactional outbox path.

Open-Meteo geocoding supplies the display name, locality, region, country, coordinates, and timezone for normal selection. The visible physical location is never derived from the timezone. Existing `WEATHER_LATITUDE`, `WEATHER_LONGITUDE`, and `WEATHER_TIMEZONE` values are optional first-run bootstrap fallback only. If they are supplied before a place has been selected, a single reverse lookup resolves a human-readable label; the fallback is never used for interactive search. No built-in coordinates or guessed city are used. Empty configuration leaves the provider idle and the UI prompts the user to choose a location.

The coordinate-bootstrap reverse lookup uses the public Nominatim service only once per first-run location resolution, not for autocomplete. Requests are serialized to at most one per second, use an identifying User-Agent, and the UI credits OpenStreetMap contributors. If lookup is unavailable, startup and the rest of the weather UI remain usable with no fabricated place label.

## Weather and atmosphere

Forecast requests explicitly select Fahrenheit, inches, and mph. Current fields include temperature, apparent temperature, WMO weather code, precipitation, and wind; concise daily context includes high/low and maximum precipitation probability. Conditions are cached by location and persisted as a provider checkpoint. The selected location's timezone-local hour drives only the atmospheric day phase; the main dashboard clock remains the user's system-local clock. Observed condition categories (clear, cloud, rain, snow, fog, or supported thunderstorm) influence the restrained CSS treatment. Missing conditions use the neutral presentation.

## Polling and meaningful changes

The shared single-instance scheduler polls every 20 minutes with a 20-second timeout, jitter, exponential backoff, cancellation, and provider `Retry-After` handling. A location selection requests one additional immediate poll. A successful poll refreshes the current-weather DTO and health timestamp, but does not by itself create a timeline event.

The event baseline is stored in the shared provider checkpoint table and advances only when a meaningful change is emitted. The current snapshot checkpoint advances on every successful poll. `weather.conditions.updated` is emitted for an initial observation, a normalized condition-category change, a temperature or apparent-temperature change of at least 2°F, precipitation change of at least 0.02 inches, wind change of at least 5 mph, daily high/low change of at least 2°F, or daily precipitation-probability change of at least 10 percentage points. Small changes update the current DTO without creating timeline noise; comparisons use the last emitted baseline so gradual changes can accumulate to a threshold.

The normalized DTO contains observation time, selected location identity, Fahrenheit current and daily temperatures, precipitation in inches, wind in mph, WMO presentation category, and precipitation probability. Health becomes stale after 45 minutes without a successful poll and retains the last successful snapshot after a poll failure. Location coordinates and provider payloads are not exposed in health or application logs.
