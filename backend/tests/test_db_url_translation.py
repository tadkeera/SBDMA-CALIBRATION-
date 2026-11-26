"""Connection-string translation for managed PostgreSQL.

Discovered by deploying to a managed provider (Supabase): their documented URL is
``…?sslmode=require``, which is the libpq spelling. Alembic's psycopg driver
understands it; SQLAlchemy's asyncpg driver does not — it forwards unknown query
parameters into ``asyncpg.connect`` and the API dies at startup with
``TypeError: connect() got an unexpected keyword argument 'sslmode'``.

None of this appears against a local database, which is why it is worth a test: the
local suite would keep passing while every managed deployment refused to boot.
"""

from __future__ import annotations

import ssl

from app.core.database import engine_url_and_connect_args


def test_sslmode_require_is_moved_into_the_driver_vocabulary() -> None:
    url, args = engine_url_and_connect_args(
        "postgresql+asyncpg://u:p@host:5432/db?sslmode=require"
    )
    assert "sslmode" not in url, "asyncpg would choke on the leftover parameter"
    assert url == "postgresql+asyncpg://u:p@host:5432/db"
    context = args["ssl"]
    assert isinstance(context, ssl.SSLContext)
    # libpq's `require` encrypts without verifying: encrypted, not certified. Mapping
    # it to a fully verifying context fails the handshake against pooler certificates.
    assert context.verify_mode == ssl.CERT_NONE
    assert context.check_hostname is False


def test_verify_full_keeps_certificate_verification() -> None:
    _, args = engine_url_and_connect_args(
        "postgresql+asyncpg://u:p@host:5432/db?sslmode=verify-full"
    )
    context = args["ssl"]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_a_local_url_needs_no_ssl_argument() -> None:
    """A plain local connection carries no TLS settings.

    The statement cache is off by default (see ``test_database_connect``), so the
    assertion is about TLS specifically rather than about an empty dict.
    """
    url, args = engine_url_and_connect_args("postgresql+asyncpg://u:p@127.0.0.1:5432/db")
    assert url == "postgresql+asyncpg://u:p@127.0.0.1:5432/db"
    assert "ssl" not in args


def test_transaction_pooler_disables_prepared_statements() -> None:
    """Supavisor/pgbouncer in transaction mode cannot keep prepared statements between
    transactions; leaving asyncpg's cache on makes queries fail intermittently."""
    url, args = engine_url_and_connect_args(
        "postgresql+asyncpg://u:p@host:6543/db?sslmode=require&prepared_statements=0"
    )
    assert "prepared_statements" not in url
    assert args["prepared_statement_cache_size"] == 0
    assert args["statement_cache_size"] == 0


def test_url_keeps_its_password_for_the_client() -> None:
    """The redacted form SQLAlchemy prints by default would break the connection if it
    ever reached the engine."""
    url, _ = engine_url_and_connect_args("postgresql+asyncpg://u:secret@host:5432/db")
    assert "secret" in url
