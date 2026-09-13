"""Spotify server-side Authorization Code flow and encrypted token lifecycle."""

from __future__ import annotations

import hmac
import ipaddress
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode, urlsplit

import httpx
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.providers.credentials import CredentialCipher, CredentialEncryptionError
from app.storage.models import ProviderConnectionRow

SPOTIFY_PROVIDER = "spotify"
SPOTIFY_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_CALLBACK_PATH = "/api/v1/providers/spotify/oauth/callback"
SPOTIFY_SCOPES = ("user-read-playback-state", "user-modify-playback-state")
STATE_TTL = timedelta(minutes=10)


class SpotifyOAuthError(RuntimeError):
    """An OAuth failure that carries only a safe, stable detail code."""

    def __init__(self, detail_code: str, *, status_code: int | None = None) -> None:
        self.detail_code = detail_code
        self.status_code = status_code
        super().__init__(detail_code)


class SpotifyConnectionStoreError(RuntimeError):
    """Stored credentials are absent, invalid, or could not be persisted."""

    def __init__(self, detail_code: str) -> None:
        self.detail_code = detail_code
        super().__init__(detail_code)


@dataclass(frozen=True, slots=True, repr=False)
class SpotifyTokens:
    access_token: str
    refresh_token: str
    expires_at: datetime
    scopes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.access_token or not self.refresh_token:
            raise ValueError("Spotify access and refresh credentials are required")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("token expiry must be timezone-aware")
        object.__setattr__(self, "expires_at", self.expires_at.astimezone(UTC))

    def __repr__(self) -> str:
        return "SpotifyTokens([REDACTED])"

    def to_json(self) -> str:
        return json.dumps(
            {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "expires_at": self.expires_at.isoformat(),
                "scopes": self.scopes,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, value: bytes) -> SpotifyTokens:
        data = json.loads(value)
        if not isinstance(data, dict):
            raise ValueError("invalid token envelope")
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=datetime.fromisoformat(data["expires_at"]),
            scopes=tuple(data.get("scopes", ())),
        )


@dataclass(frozen=True, slots=True)
class SpotifyConnectionInfo:
    connected: bool
    status: str
    connected_at: datetime | None


class ConnectionStore(Protocol):
    async def load_tokens(self) -> SpotifyTokens | None: ...

    async def save_tokens(self, tokens: SpotifyTokens) -> None: ...

    async def mark_reconnect_required(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def connection_info(self) -> SpotifyConnectionInfo: ...


class OAuthStateStore:
    """Single-process, expiring, one-use CSRF states for Spotify OAuth callbacks."""

    def __init__(
        self,
        *,
        ttl: timedelta = STATE_TTL,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("OAuth state TTL must be positive")
        self._ttl = ttl
        self._clock = clock
        self._states: dict[str, datetime] = {}

    def create(self) -> str:
        now = _utc(self._clock())
        self._discard_expired(now)
        state = secrets.token_urlsafe(32)
        self._states[state] = now + self._ttl
        return state

    def consume(self, supplied_state: str | None) -> bool:
        now = _utc(self._clock())
        self._discard_expired(now)
        if not supplied_state:
            return False
        for expected in tuple(self._states):
            try:
                matches = hmac.compare_digest(expected, supplied_state)
            except TypeError:
                return False
            if matches:
                del self._states[expected]
                return True
        return False

    def _discard_expired(self, now: datetime) -> None:
        for state, expires_at in tuple(self._states.items()):
            if expires_at <= now:
                del self._states[state]


class SqlAlchemySpotifyConnectionStore:
    """Adapter over the shared encrypted provider_connections storage."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        settings_getter: Callable[[], Settings] = get_settings,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._settings_getter = settings_getter
        self._clock = clock

    async def load_tokens(self) -> SpotifyTokens | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(ProviderConnectionRow).where(
                    ProviderConnectionRow.provider == SPOTIFY_PROVIDER
                )
            )
            if row is None or row.status != "connected" or row.encrypted_credentials is None:
                return None
            try:
                plaintext = self._cipher().decrypt(row.encrypted_credentials)
                return SpotifyTokens.from_json(plaintext)
            except (
                CredentialEncryptionError,
                KeyError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                raise SpotifyConnectionStoreError("stored_credentials_unavailable") from exc

    async def save_tokens(self, tokens: SpotifyTokens) -> None:
        try:
            encrypted = self._cipher().encrypt(tokens.to_json())
        except CredentialEncryptionError as exc:
            raise SpotifyConnectionStoreError("credential_encryption_unavailable") from exc
        now = _utc(self._clock())
        async with self._session_factory() as session:
            async with session.begin():
                row = await session.scalar(
                    select(ProviderConnectionRow).where(
                        ProviderConnectionRow.provider == SPOTIFY_PROVIDER
                    )
                )
                if row is None:
                    row = ProviderConnectionRow(provider=SPOTIFY_PROVIDER, status="connected")
                    session.add(row)
                row.status = "connected"
                row.encrypted_credentials = encrypted
                row.scopes = list(tokens.scopes)
                row.connected_at = row.connected_at or now

    async def mark_reconnect_required(self) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                row = await session.scalar(
                    select(ProviderConnectionRow).where(
                        ProviderConnectionRow.provider == SPOTIFY_PROVIDER
                    )
                )
                if row is not None:
                    row.status = "degraded"
                    row.encrypted_credentials = None
                    row.scopes = []

    async def disconnect(self) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                row = await session.scalar(
                    select(ProviderConnectionRow).where(
                        ProviderConnectionRow.provider == SPOTIFY_PROVIDER
                    )
                )
                if row is not None:
                    row.status = "disconnected"
                    row.encrypted_credentials = None
                    row.scopes = []
                    row.connected_at = None

    async def connection_info(self) -> SpotifyConnectionInfo:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(ProviderConnectionRow).where(
                    ProviderConnectionRow.provider == SPOTIFY_PROVIDER
                )
            )
            if row is None:
                return SpotifyConnectionInfo(False, "disconnected", None)
            connected = row.status == "connected" and row.encrypted_credentials is not None
            return SpotifyConnectionInfo(connected, row.status, row.connected_at)

    def _cipher(self) -> CredentialCipher:
        return CredentialCipher(self._settings_getter().credential_encryption_key)


class SpotifyOAuthService:
    def __init__(
        self,
        store: ConnectionStore,
        *,
        settings_getter: Callable[[], Settings] = get_settings,
        http_client: httpx.AsyncClient | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        on_reconnect_required: Callable[[], None] | None = None,
    ) -> None:
        self.store = store
        self._settings_getter = settings_getter
        self._http_client = http_client
        self._clock = clock
        self._on_reconnect_required = on_reconnect_required

    def authorization_url(self, state: str) -> str:
        settings = self._complete_settings()
        query = urlencode(
            {
                "client_id": settings.spotify_client_id,
                "response_type": "code",
                "redirect_uri": settings.spotify_redirect_uri,
                "scope": " ".join(SPOTIFY_SCOPES),
                "state": state,
            }
        )
        return f"{SPOTIFY_AUTHORIZE_URL}?{query}"

    async def exchange_authorization_code(self, code: str) -> SpotifyTokens:
        if not code:
            raise SpotifyOAuthError("authorization_code_missing")
        settings = self._complete_settings()
        response = await self._post_token(
            settings,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.spotify_redirect_uri,
            },
        )
        data = _token_response(response)
        refresh_token = data.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise SpotifyOAuthError("refresh_token_missing", status_code=response.status_code)
        tokens = self._make_tokens(
            data, refresh_token=refresh_token, fallback_scopes=SPOTIFY_SCOPES
        )
        await self.store.save_tokens(tokens)
        return tokens

    async def refresh(self, existing: SpotifyTokens) -> SpotifyTokens:
        settings = self._complete_settings()
        response = await self._post_token(
            settings,
            {"grant_type": "refresh_token", "refresh_token": existing.refresh_token},
        )
        data = _token_response(response, allow_invalid_grant=True)
        if data is None:
            await self.store.mark_reconnect_required()
            if self._on_reconnect_required is not None:
                self._on_reconnect_required()
            raise SpotifyOAuthError("authorization_expired", status_code=response.status_code)
        rotated_refresh = data.get("refresh_token")
        refresh_token = (
            rotated_refresh
            if isinstance(rotated_refresh, str) and rotated_refresh
            else existing.refresh_token
        )
        tokens = self._make_tokens(
            data, refresh_token=refresh_token, fallback_scopes=existing.scopes
        )
        await self.store.save_tokens(tokens)
        return tokens

    def _make_tokens(
        self,
        data: dict[str, object],
        *,
        refresh_token: str,
        fallback_scopes: tuple[str, ...],
    ) -> SpotifyTokens:
        access_token = data.get("access_token")
        expires_in = data.get("expires_in")
        if (
            not isinstance(access_token, str)
            or not access_token
            or not isinstance(expires_in, int)
            or isinstance(expires_in, bool)
            or expires_in <= 0
        ):
            raise SpotifyOAuthError("token_response_invalid")
        scope_value = data.get("scope")
        scopes = (
            tuple(scope_value.split())
            if isinstance(scope_value, str) and scope_value.strip()
            else fallback_scopes
        )
        return SpotifyTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=_utc(self._clock()) + timedelta(seconds=expires_in),
            scopes=scopes,
        )

    async def _post_token(self, settings: Settings, data: dict[str, str]) -> httpx.Response:
        client_id = _required_text(settings.spotify_client_id)
        client_secret = _secret_text(settings.spotify_client_secret)
        try:
            if self._http_client is not None:
                response = await self._http_client.post(
                    SPOTIFY_TOKEN_URL,
                    data=data,
                    auth=(client_id, client_secret),
                    timeout=10,
                )
            else:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.post(
                        SPOTIFY_TOKEN_URL,
                        data=data,
                        auth=(client_id, client_secret),
                    )
        except httpx.HTTPError:
            raise SpotifyOAuthError("token_endpoint_unavailable") from None
        return response

    def _complete_settings(self) -> Settings:
        settings = self._settings_getter()
        if not (
            _required_text(settings.spotify_client_id)
            and _secret_text(settings.spotify_client_secret)
            and _required_text(settings.spotify_redirect_uri)
        ):
            raise SpotifyOAuthError("configuration_missing")
        if not _secret_text(settings.credential_encryption_key):
            raise SpotifyOAuthError("credential_encryption_unavailable")
        try:
            CredentialCipher(settings.credential_encryption_key)
        except CredentialEncryptionError as exc:
            raise SpotifyOAuthError("credential_encryption_unavailable") from exc
        _validate_redirect_uri(settings.spotify_redirect_uri)
        return settings


def _token_response(
    response: httpx.Response, *, allow_invalid_grant: bool = False
) -> dict[str, object] | None:
    try:
        data = response.json()
    except ValueError as exc:
        raise SpotifyOAuthError("token_response_invalid", status_code=response.status_code) from exc
    if (
        allow_invalid_grant
        and response.status_code == 400
        and isinstance(data, dict)
        and data.get("error") == "invalid_grant"
    ):
        return None
    if response.status_code != 200 or not isinstance(data, dict):
        raise SpotifyOAuthError("token_exchange_failed", status_code=response.status_code)
    return data


def _validate_redirect_uri(value: str | None) -> None:
    if not value:
        raise SpotifyOAuthError("redirect_uri_invalid")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise SpotifyOAuthError("redirect_uri_invalid") from exc
    if port == 0:
        raise SpotifyOAuthError("redirect_uri_invalid")
    try:
        host = parsed.hostname
        loopback = bool(host and ipaddress.ip_address(host).is_loopback)
    except ValueError:
        host = parsed.hostname
        loopback = False
    valid_scheme = parsed.scheme == "https" or (parsed.scheme == "http" and loopback)
    if (
        not valid_scheme
        or not host
        or host.lower() == "localhost"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.path != SPOTIFY_CALLBACK_PATH
    ):
        raise SpotifyOAuthError("redirect_uri_invalid")


def is_spotify_configured(settings: Settings) -> bool:
    if not settings.provider_configuration()["spotify"]:
        return False
    try:
        CredentialCipher(settings.credential_encryption_key)
        _validate_redirect_uri(settings.spotify_redirect_uri)
    except (CredentialEncryptionError, SpotifyOAuthError):
        return False
    return True


def _required_text(value: str | None) -> str:
    return value.strip() if isinstance(value, str) else ""


def _secret_text(value: SecretStr | str | None) -> str:
    if isinstance(value, SecretStr):
        return value.get_secret_value().strip()
    return value.strip() if isinstance(value, str) else ""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)
