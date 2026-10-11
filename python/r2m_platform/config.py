"""Typed environment settings. Fails fast on missing secrets; never logs values."""
import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    database_ssl_mode: str  # verify-full (default) | disable (loopback hosts only)
    database_ca_cert: str | None
    session_signing_key: str
    sdk_ingest_token: str
    grant_signing_key: str
    internal_api_url: str
    keewano_enabled: bool
    session_ttl_seconds: int = 8 * 3600
    grant_ttl_seconds: int = 60  # SDK contract: expires_at <= 60 s ahead
    runtime_approval_ttl_seconds: int = 900

    @property
    def is_demo(self) -> bool:
        return self.app_env == "demo"


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"missing required environment variable {name}")
    return value


def load_settings() -> Settings:
    s = Settings(
        app_env=_required("APP_ENV"),
        database_url=_required("DATABASE_URL"),
        database_ssl_mode=os.environ.get("DATABASE_SSL_MODE", "verify-full").strip(),
        database_ca_cert=os.environ.get("DATABASE_CA_CERT", "").strip() or None,
        session_signing_key=_required("SESSION_SIGNING_KEY"),
        sdk_ingest_token=_required("SDK_INGEST_TOKEN"),
        # SDK contract: grants are signed with R2M_GRANT_SIGNING_KEY, falling back to SDK_INGEST_TOKEN.
        grant_signing_key=os.environ.get("R2M_GRANT_SIGNING_KEY", "").strip() or _required("SDK_INGEST_TOKEN"),
        internal_api_url=_required("R2M_INTERNAL_API_URL"),
        keewano_enabled=os.environ.get("KEEWANO_ENABLED", "false").lower() == "true",
    )
    if s.database_ssl_mode not in ("verify-full", "disable"):
        raise ConfigError("DATABASE_SSL_MODE must be verify-full or disable")
    if s.database_ssl_mode == "disable" and urlparse(s.database_url).hostname not in LOCAL_HOSTS:
        raise ConfigError("DATABASE_SSL_MODE=disable is only allowed for a loopback database")
    if s.database_ca_cert and not os.path.isfile(s.database_ca_cert):
        raise ConfigError("DATABASE_CA_CERT does not point to a readable file")
    for name, value in (("SESSION_SIGNING_KEY", s.session_signing_key), ("SDK_INGEST_TOKEN", s.sdk_ingest_token),
                        ("R2M_GRANT_SIGNING_KEY", s.grant_signing_key)):
        if len(value) < 32:
            raise ConfigError(f"{name} must be at least 32 characters")
    if s.keewano_enabled:
        for name in ("KEEWANO_API_KEY", "KEEWANO_PAT"):
            _required(name)
    return s


@lru_cache
def get_settings() -> Settings:
    return load_settings()
