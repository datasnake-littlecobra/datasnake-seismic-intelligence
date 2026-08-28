"""Loads config_vibration.yaml the same way the rest of this repo loads
config.yaml — same pattern, separate file (see that file's header comment
for why it's kept separate from the existing config.yaml)."""

import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[4]
load_dotenv(ROOT / ".env")


@lru_cache
def get_config() -> dict:
    with open(ROOT / "config_vibration.yaml") as f:
        return yaml.safe_load(f)


def get_database_url() -> str | URL:
    """Prefers building a connection from individual DB_HOST/DB_PORT/
    DB_NAME/DB_USER/DB_PASSWORD env vars over a single pre-assembled URL
    string, when the individual ones are present.

    Why: a password containing special characters (e.g. '@') breaks a
    pre-assembled connection-string URL unless it's percent-encoded by
    whoever sets it — an easy, easy-to-miss mistake (hit for real in this
    project: an unencoded '@' in the password got parsed as part of the
    hostname). `sqlalchemy.engine.URL.create()` handles that encoding for
    every component automatically, so this class of bug can't recur for
    anyone using the individual vars.

    DATABASE_POOLER_URL/DATABASE_URL are still supported as a fallback for
    anyone who already has a correctly-encoded one.
    """
    host = os.getenv("DB_HOST")
    password = os.getenv("DB_PASSWORD")
    user = os.getenv("DB_USER")
    if host and password and user:
        # No default for DB_USER: Supabase's pooler requires the project-ref
        # suffix (e.g. "postgres.abcdefgh"), not plain "postgres" — a silent
        # default here would produce a wrong-but-plausible-looking value
        # instead of a clear error.
        return URL.create(
            drivername="postgresql+psycopg2",
            username=user,
            password=password,
            host=host,
            port=int(os.getenv("DB_PORT", "6543")),
            database=os.getenv("DB_NAME", "postgres"),
        )

    url = os.getenv("DATABASE_POOLER_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "Neither DB_HOST+DB_USER+DB_PASSWORD nor DATABASE_POOLER_URL/"
            "DATABASE_URL is set — see .env.example. Prefer the individual "
            "DB_* variables: they avoid needing to percent-encode special "
            "characters in the password by hand."
        )
    return url
