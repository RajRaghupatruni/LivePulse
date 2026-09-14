"""Server-side Google OAuth authorization-code and refresh handling."""

import asyncio
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.providers.credentials import CredentialCipher, CredentialEncryptionError
from app.providers.oauth_completion import OAuthCompletionMode
from app.storage.models import ProviderConnectionRow

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_STATE_STORES: dict[str, "OAuthStateStore"] = {}


class OAuthAccessLogRedactionFilter(logging.Filter):
    """Remove OAuth callback query values from Uvicorn access log records."""

    _callback = re.compile(r"(/api/v1/providers/gmail/oauth/callback)\?[^\s\"]+")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            # Uvicorn's AccessFormatter unpacks all five access arguments. Redact the
            # path in place while retaining that tuple's shape for the formatter.
            record.args = tuple(
                self._redact(value) if isinstance(value, str) else value for value in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: self._redact(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        elif isinstance(record.msg, str):
            record.msg = self._redact(record.msg)
        return True

    @classmethod
    def _redact(cls, value: str) -> str:
        return cls._callback.sub(r"\1?[REDACTED]", value)


def install_oauth_access_log_filter() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, OAuthAccessLogRedactionFilter) for item in access_logger.filters):
        access_logger.addFilter(OAuthAccessLogRedactionFilter())


class OAuthError(RuntimeError):
    """An OAuth failure with a safe, stable detail code."""

    def __init__(
        self,
        detail_code: str,
        *,
        completion_mode: OAuthCompletionMode | None = None,
    ) -> None:
        self.detail_code = detail_code
        self.completion_mode = completion_mode
        super().__init__(detail_code)


class OAuthStateStore:
    """One-time, expiring server-side OAuth state values signed with the client secret."""

    def __init__(self, secret: SecretStr | str, *, ttl: timedelta = timedelta(minutes=10)) -> None:
        self._secret = secret.get_secret_value() if isinstance(secret, SecretStr) else secret
        self._ttl = ttl
        self._issued: dict[str, tuple[float, OAuthCompletionMode]] = {}
        self._lock = asyncio.Lock()

    async def issue(
        self,
        completion_mode: OAuthCompletionMode | str = OAuthCompletionMode.BROWSER,
    ) -> str:
        if not isinstance(completion_mode, OAuthCompletionMode):
            completion_mode = OAuthCompletionMode(completion_mode)
        nonce = secrets.token_urlsafe(32)
        signature = hmac.new(self._secret.encode(), nonce.encode(), hashlib.sha256).hexdigest()
        state = f"{nonce}.{signature}"
        async with self._lock:
            self._prune(time.monotonic())
            self._issued[state] = (time.monotonic() + self._ttl.total_seconds(), completion_mode)
        return state

    async def consume(self, state: str) -> bool:
        return await self.consume_mode(state) is not None

    async def consume_mode(self, state: str) -> OAuthCompletionMode | None:
        if not isinstance(state, str) or len(state) > 200:
            return None
        nonce, separator, signature = state.partition(".")
        if not separator or not nonce or not signature:
            return None
        expected = hmac.new(self._secret.encode(), nonce.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        now = time.monotonic()
        async with self._lock:
            issued = self._issued.pop(state, None)
            self._prune(now)
        if issued is None:
            return None
        expires_at, completion_mode = issued
        return completion_mode if expires_at >= now else None

    def _prune(self, now: float) -> None:
        self._issued = {
            state: issued for state, issued in self._issued.items() if issued[0] >= now
        }
        if len(self._issued) > 1000:
            for state, _issued in sorted(
                self._issued.items(), key=lambda pair: pair[1][0]
            )[:500]:
                self._issued.pop(state, None)


def state_store_for(secret: SecretStr | str) -> OAuthStateStore:
    raw = secret.get_secret_value() if isinstance(secret, SecretStr) else secret
    key = hashlib.sha256(raw.encode()).hexdigest()
    if key not in _STATE_STORES:
        _STATE_STORES[key] = OAuthStateStore(raw)
    return _STATE_STORES[key]


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    access_token: SecretStr
    refresh_token: SecretStr | None = None
    token_type: str = Field(default="Bearer")
    expires_in: int = Field(gt=0, le=31_536_000)
    scope: str = ""


class StoredTokenSet(BaseModel):
    model_config = ConfigDict(extra="forbid", repr=False)

    access_token: SecretStr
    refresh_token: SecretStr
    expires_at: datetime
    token_type: str = "Bearer"


@dataclass(slots=True)
class GoogleOAuth:
    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    http: httpx.AsyncClient
    states: OAuthStateStore | None = None

    def __post_init__(self) -> None:
        if self.states is None and self.settings.google_client_secret:
            self.states = state_store_for(self.settings.google_client_secret)

    def authorization_url(self, state: str) -> str:
        redirect_uri = _required(self.settings.google_redirect_uri, "oauth_not_configured")
        client_id = _required(self.settings.google_client_id, "oauth_not_configured")
        return f"{GOOGLE_AUTH_URL}?{
            urlencode(
                {
                    'client_id': client_id,
                    'redirect_uri': redirect_uri,
                    'response_type': 'code',
                    'scope': GMAIL_READONLY_SCOPE,
                    'access_type': 'offline',
                    'prompt': 'consent',
                    'state': state,
                }
            )
        }"

    async def begin(
        self,
        completion_mode: OAuthCompletionMode = OAuthCompletionMode.BROWSER,
    ) -> str:
        if not self.settings.provider_configuration()["gmail"] or self.states is None:
            raise OAuthError("oauth_not_configured")
        if not encryption_key_configured(self.settings):
            raise OAuthError("credential_encryption_unavailable")
        return self.authorization_url(await self.states.issue(completion_mode))

    async def consume_state(self, state: str) -> OAuthCompletionMode:
        if not self.settings.provider_configuration()["gmail"] or self.states is None:
            raise OAuthError("oauth_not_configured")
        completion_mode = await self.states.consume_mode(state)
        if completion_mode is None:
            raise OAuthError("oauth_state_invalid")
        return completion_mode

    async def complete(self, *, state: str, code: str) -> OAuthCompletionMode:
        completion_mode = await self.consume_state(state)
        try:
            await self._complete_authorized(code=code)
        except OAuthError as exc:
            raise OAuthError(exc.detail_code, completion_mode=completion_mode) from exc
        except httpx.HTTPError as exc:
            raise OAuthError(
                "authorization_exchange_failed", completion_mode=completion_mode
            ) from exc
        return completion_mode

    async def _complete_authorized(self, *, code: str) -> None:
        if not self.settings.provider_configuration()["gmail"]:
            raise OAuthError("oauth_not_configured")
        if not code or len(code) > 4096:
            raise OAuthError("authorization_code_invalid")
        token = await self._exchange_code(code)
        refresh = token.refresh_token
        if refresh is None:
            # Google may omit it on repeat consent if the account has already granted access.
            async with self.session_factory() as session:
                old = await session.scalar(
                    select(ProviderConnectionRow).where(ProviderConnectionRow.provider == "gmail")
                )
                if old is not None and old.encrypted_credentials is not None:
                    stored = _decrypt_tokens(self.settings, old.encrypted_credentials)
                    refresh = stored.refresh_token
        if refresh is None:
            raise OAuthError("refresh_token_missing")
        _validate_scopes(token.scope)
        encrypted = _encrypt_tokens(
            self.settings,
            StoredTokenSet(
                access_token=token.access_token,
                refresh_token=refresh,
                expires_at=datetime.now(UTC) + timedelta(seconds=token.expires_in),
            ),
        )
        async with self.session_factory() as session:
            async with session.begin():
                row = await session.scalar(
                    select(ProviderConnectionRow).where(ProviderConnectionRow.provider == "gmail")
                )
                if row is None:
                    row = ProviderConnectionRow(provider="gmail", status="connected")
                    session.add(row)
                row.status = "connected"
                row.encrypted_credentials = encrypted
                row.scopes = [GMAIL_READONLY_SCOPE]
                row.connected_at = datetime.now(UTC)

    async def refresh(self, refresh_token: SecretStr) -> TokenResponse:
        form = {
            "client_id": _required(self.settings.google_client_id, "oauth_not_configured"),
            "client_secret": _required_secret(
                self.settings.google_client_secret, "oauth_not_configured"
            ),
            "refresh_token": refresh_token.get_secret_value(),
            "grant_type": "refresh_token",
        }
        response = await self.http.post(GOOGLE_TOKEN_URL, data=form)
        if response.status_code >= 400:
            if response.status_code in {400, 401}:
                raise OAuthError("reconnect_required")
            raise OAuthError("token_refresh_failed")
        token = _parse_token_response(response)
        if token.scope:
            _validate_scopes(token.scope)
        return token

    async def _exchange_code(self, code: str) -> TokenResponse:
        form = {
            "code": code,
            "client_id": _required(self.settings.google_client_id, "oauth_not_configured"),
            "client_secret": _required_secret(
                self.settings.google_client_secret, "oauth_not_configured"
            ),
            "redirect_uri": _required(self.settings.google_redirect_uri, "oauth_not_configured"),
            "grant_type": "authorization_code",
        }
        response = await self.http.post(GOOGLE_TOKEN_URL, data=form)
        if response.status_code >= 400:
            raise OAuthError("authorization_exchange_failed")
        token = _parse_token_response(response)
        _validate_scopes(token.scope)
        return token


@dataclass(slots=True)
class GmailTokenManager:
    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    oauth: GoogleOAuth
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _cached: StoredTokenSet | None = field(default=None, repr=False)

    async def access_token(self, *, force_refresh: bool = False) -> SecretStr:
        async with self._lock:
            if (
                not force_refresh
                and self._cached is not None
                and self._cached.expires_at > datetime.now(UTC) + timedelta(seconds=60)
            ):
                return self._cached.access_token
            async with self.session_factory() as session:
                async with session.begin():
                    row = await session.scalar(
                        select(ProviderConnectionRow).where(
                            ProviderConnectionRow.provider == "gmail"
                        )
                    )
                    if row is None or row.encrypted_credentials is None:
                        raise OAuthError("authorization_required")
                    if row.status != "connected":
                        raise OAuthError("reconnect_required")
                    encrypted = row.encrypted_credentials
                    stored = _decrypt_tokens(self.settings, encrypted)
            self._cached = stored
            # Close the read session before the token HTTP request so no database
            # connection is held while Google responds.
            if not force_refresh and stored.expires_at > datetime.now(UTC) + timedelta(seconds=60):
                return stored.access_token
            try:
                refreshed = await self.oauth.refresh(stored.refresh_token)
            except OAuthError as exc:
                if exc.detail_code == "reconnect_required":
                    await self.reconnect_required()
                    raise
                raise
            updated = StoredTokenSet(
                access_token=refreshed.access_token,
                refresh_token=refreshed.refresh_token or stored.refresh_token,
                expires_at=datetime.now(UTC) + timedelta(seconds=refreshed.expires_in),
            )
            async with self.session_factory() as update_session:
                async with update_session.begin():
                    update_row = await update_session.scalar(
                        select(ProviderConnectionRow).where(
                            ProviderConnectionRow.provider == "gmail"
                        )
                    )
                    if update_row is None:
                        raise OAuthError("authorization_required")
                    update_row.encrypted_credentials = _encrypt_tokens(self.settings, updated)
            self._cached = updated
            return updated.access_token

    async def reconnect_required(self) -> None:
        self._cached = None
        async with self.session_factory() as session:
            async with session.begin():
                row = await session.scalar(
                    select(ProviderConnectionRow).where(ProviderConnectionRow.provider == "gmail")
                )
                if row is not None:
                    row.status = "degraded"


def _parse_token_response(response: httpx.Response) -> TokenResponse:
    try:
        return TokenResponse.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise OAuthError("token_response_invalid") from exc


def _validate_scopes(raw_scopes: str) -> None:
    scopes = set(raw_scopes.split())
    if scopes != {GMAIL_READONLY_SCOPE}:
        raise OAuthError("read_only_scope_required")


def _encrypt_tokens(settings: Settings, token: StoredTokenSet):
    try:
        cipher = CredentialCipher(settings.credential_encryption_key)
    except CredentialEncryptionError as exc:
        raise OAuthError("credential_encryption_unavailable") from exc
    serialized = json.dumps(
        {
            "access_token": token.access_token.get_secret_value(),
            "refresh_token": token.refresh_token.get_secret_value(),
            "expires_at": token.expires_at.astimezone(UTC).isoformat(),
            "token_type": token.token_type,
        },
        separators=(",", ":"),
    )
    return cipher.encrypt(serialized)


def _decrypt_tokens(settings: Settings, encrypted) -> StoredTokenSet:
    try:
        cipher = CredentialCipher(settings.credential_encryption_key)
        raw = json.loads(cipher.decrypt(encrypted))
        return StoredTokenSet.model_validate(raw)
    except (CredentialEncryptionError, ValueError, TypeError, ValidationError) as exc:
        raise OAuthError("stored_credentials_unavailable") from exc


def _required(value: str | None, detail: str) -> str:
    if not value or not value.strip():
        raise OAuthError(detail)
    return value


def _required_secret(value: SecretStr | None, detail: str) -> str:
    if value is None or not value.get_secret_value().strip():
        raise OAuthError(detail)
    return value.get_secret_value()


def encryption_key_configured(settings: Settings) -> bool:
    key = settings.credential_encryption_key
    if key is None or not key.get_secret_value().strip():
        return False
    try:
        CredentialCipher(key)
    except CredentialEncryptionError:
        return False
    return True
