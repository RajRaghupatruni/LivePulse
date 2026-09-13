# Weather provider

Weather uses the public Open-Meteo `/v1/forecast` endpoint and requires no API key. Provider DTOs,
HTTP details, WMO code normalization, and units remain inside this package. The clean normalized
current-weather service is exposed at `GET /api/v1/providers/weather/current`; freshness is
available at `GET /api/v1/providers/weather/health`.

## Configuration and fields

Set `WEATHER_LATITUDE`, `WEATHER_LONGITUDE`, and `WEATHER_TIMEZONE` in the ignored local `.env`.
All three are required. Missing location configuration disables polling without using a built-in
or guessed location. Coordinates are sent only to Open-Meteo and are not included in health,
normalized DTOs, or application logs.

The adapter asks for current `temperature_2m`, `apparent_temperature`, `weather_code`,
`precipitation`, and `wind_speed_10m`, plus daily high/low temperature and maximum precipitation
probability. Requests explicitly select Fahrenheit, inches, and mph. Sunrise/sunset are omitted
because they are not needed for the current second-monitor context.

## Polling and meaningful changes

The shared single-instance scheduler polls every 20 minutes with a 20-second timeout, jitter,
exponential backoff, cancellation, and provider `Retry-After` handling. A successful poll refreshes
the current-weather DTO and its health timestamp, but does not by itself create a timeline event.

The event baseline is stored in the shared provider checkpoint table and advances only when a
meaningful change is emitted. The current snapshot checkpoint advances on every successful poll.
`weather.conditions.updated` is emitted for an initial observation, a normalized condition-category
change, a temperature or apparent-temperature change of at least 2°F, precipitation change of at
least 0.02 inches, wind change of at least 5 mph, daily high/low change of at least 2°F, or daily
precipitation-probability change of at least 10 percentage points. Small changes are folded into
the latest current DTO without creating timeline noise; comparisons use the last emitted baseline
so gradual changes can accumulate to a threshold.

The normalized DTO reports its configured timezone, provider observation time, Fahrenheit current
and daily temperatures, precipitation in inches, wind in mph, WMO presentation category, and
precipitation probability. Health is fresh through 45 minutes after a successful poll, then
degraded/stale; a poll failure is reported separately while retaining the last successful snapshot.
