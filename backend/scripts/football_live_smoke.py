"""Manual two-request API-Football connectivity smoke check."""

import asyncio

from app.core.config import get_settings
from app.providers.football.api import FootballApiClient
from app.providers.football.leagues import resolve_league_catalog


async def main() -> int:
    settings = get_settings()
    if settings.api_football_key is None or not settings.api_football_key.get_secret_value().strip():
        print("API_FOOTBALL_KEY is not set; no provider request was made.")
        return 2

    client = FootballApiClient(settings.api_football_key)
    try:
        # Restrict the metadata check to one known name so the smoke stays at
        # two requests even when the full current-league catalog is paginated.
        leagues = await client.leagues_search("Premier League")
        catalog = resolve_league_catalog(leagues)
        fixtures = await client.live_fixtures(list(catalog.values())) if catalog else []
        print(
            "API-Football smoke check passed: "
            f"resolved {len(catalog)} locked competitions; "
            f"received {len(fixtures)} relevant live fixture(s)."
        )
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
