"""API-resolved competition names and aliases for the locked football catalog."""

import re
import unicodedata
from dataclasses import dataclass

from app.providers.football.models import LeagueRecord


@dataclass(frozen=True, slots=True)
class CompetitionSpec:
    canonical_name: str
    aliases: frozenset[str]
    countries: frozenset[str]


LOCKED_COMPETITIONS = (
    CompetitionSpec("Premier League", frozenset({"premier league", "epl"}), frozenset({"england"})),
    CompetitionSpec("La Liga", frozenset({"la liga", "laliga"}), frozenset({"spain"})),
    CompetitionSpec("Bundesliga", frozenset({"bundesliga"}), frozenset({"germany"})),
    CompetitionSpec("Ligue 1", frozenset({"ligue 1"}), frozenset({"france"})),
    CompetitionSpec(
        "EFL Championship",
        frozenset({"efl championship", "championship"}),
        frozenset({"england"}),
    ),
    CompetitionSpec(
        "UEFA Champions League",
        frozenset({"uefa champions league", "champions league", "ucl"}),
        frozenset({"europe", "world"}),
    ),
    CompetitionSpec(
        "UEFA Europa League",
        frozenset({"uefa europa league", "europa league", "uel"}),
        frozenset({"europe", "world"}),
    ),
    CompetitionSpec("FA Cup", frozenset({"fa cup"}), frozenset({"england"})),
    CompetitionSpec(
        "Carabao Cup",
        frozenset({"carabao cup", "league cup", "efl cup"}),
        frozenset({"england"}),
    ),
    CompetitionSpec("Serie A", frozenset({"serie a"}), frozenset({"italy"})),
    CompetitionSpec(
        "MLS",
        frozenset({"mls", "major league soccer"}),
        frozenset({"usa", "united states"}),
    ),
)


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", value.casefold().replace("&", "and")).strip()


def competition_spec(name: str, country: str | None = None) -> CompetitionSpec | None:
    normalized = normalize_name(name)
    normalized_country = normalize_name(country or "")
    for spec in LOCKED_COMPETITIONS:
        if normalized in spec.aliases:
            if not normalized_country or normalized_country in spec.countries:
                return spec
    return None


def resolve_league_catalog(records: list[LeagueRecord]) -> dict[str, int]:
    """Resolve locked competitions from provider metadata; ambiguous matches are omitted."""

    candidates: dict[str, set[int]] = {spec.canonical_name: set() for spec in LOCKED_COMPETITIONS}
    for record in records:
        country = record.country.name if hasattr(record.country, "name") else record.country
        spec = competition_spec(record.league.name, country)
        if spec is None:
            continue
        candidates[spec.canonical_name].add(record.league.id)
    return {canonical: next(iter(ids)) for canonical, ids in candidates.items() if len(ids) == 1}


def resolve_league_metadata(
    records: list[LeagueRecord],
) -> tuple[dict[str, int], dict[str, int]]:
    """Return resolved provider IDs plus current season years from the same metadata."""

    catalog = resolve_league_catalog(records)
    seasons: dict[str, set[int]] = {canonical: set() for canonical in catalog}
    for record in records:
        country = record.country.name if hasattr(record.country, "name") else record.country
        spec = competition_spec(record.league.name, country)
        if spec and catalog.get(spec.canonical_name) == record.league.id:
            seasons[spec.canonical_name].update(
                season.year for season in record.seasons if season.current
            )
    current_seasons = {
        canonical: next(iter(years)) for canonical, years in seasons.items() if len(years) == 1
    }
    return catalog, current_seasons


def canonical_competition(name: str, country: str | None = None) -> str | None:
    spec = competition_spec(name, country)
    return spec.canonical_name if spec else None
