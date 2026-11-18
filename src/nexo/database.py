"""SQLite: transacciones, integridad y migraciones; sin creación implícita de tablas."""

from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import (JSON, Boolean, CheckConstraint, Column, ForeignKey, Index, Integer,
                        MetaData, String, Table, URL, create_engine, event, text)
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

metadata = MetaData()
administrators = Table(
    "administrators", metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(64), nullable=False, unique=True),
    Column("password_hash", String(256), nullable=False),
    Column("active", Boolean(create_constraint=True), nullable=False),
    Column("created_at", Integer, nullable=False),
    Column("updated_at", Integer, nullable=False),
    CheckConstraint("id = 1", name="single_principal"),
    CheckConstraint("length(username) BETWEEN 3 AND 64", name="username_length"),
)
sessions = Table(
    "admin_sessions", metadata,
    Column("id", Integer, primary_key=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("administrator_id", ForeignKey("administrators.id"), nullable=False),
    Column("created_at", Integer, nullable=False),
    Column("expires_at", Integer, nullable=False),
    Column("revoked", Boolean(create_constraint=True), nullable=False),
    CheckConstraint("expires_at = created_at + 3600", name="absolute_expiry"),
    CheckConstraint("length(token_hash) = 64", name="token_hash_length"),
)
Index("single_active_session", sessions.c.administrator_id, unique=True,
      sqlite_where=sessions.c.revoked == False)  # noqa: E712
audit = Table(
    "security_audit", metadata,
    Column("id", Integer, primary_key=True),
    Column("occurred_at", Integer, nullable=False, index=True),
    Column("event", String(40), nullable=False, index=True),
    Column("administrator_id", ForeignKey("administrators.id"), nullable=True),
    Column("result", String(20), nullable=False),
    Column("reason", String(40), nullable=True),
    Column("subject_id", String(32), nullable=True),
)

terminals = Table(
    "terminals", metadata,
    Column("id", String(32), primary_key=True),
    Column("name", String(80), nullable=False),
    Column("created_at", Integer, nullable=False),
    Column("last_activity", Integer, nullable=False),
    Column("revoked_at", Integer),
    Column("voice_config", JSON, nullable=False),
    Column("credential_hash", String(64), nullable=False, unique=True),
    Column("expires_at", Integer, nullable=False),
    CheckConstraint("length(name) BETWEEN 1 AND 80", name="terminal_name_length"),
    CheckConstraint("length(credential_hash) = 64", name="terminal_digest_length"),
    CheckConstraint("expires_at > created_at", name="terminal_expiry"),
)
terminal_permissions = Table(
    "terminal_permissions", metadata,
    Column("terminal_id", ForeignKey("terminals.id", ondelete="CASCADE"), primary_key=True),
    Column("permission", String(80), primary_key=True),
)
pairing_codes = Table(
    "pairing_codes", metadata,
    Column("id", String(32), primary_key=True),
    Column("code_hash", String(64), nullable=False, unique=True),
    Column("created_at", Integer, nullable=False),
    Column("expires_at", Integer, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("consumed_at", Integer),
    Column("revoked_at", Integer),
    Column("permissions", JSON, nullable=False),
    CheckConstraint("expires_at = created_at + 300", name="pairing_expiry"),
    CheckConstraint("attempts BETWEEN 0 AND 5", name="pairing_attempts"),
    CheckConstraint("length(code_hash) = 64", name="pairing_digest_length"),
)
pairing_rate = Table(
    "pairing_rate", metadata,
    Column("id", Integer, primary_key=True),
    Column("window_start", Integer, nullable=False),
    Column("attempts", Integer, nullable=False),
    CheckConstraint("id = 1", name="single_pairing_rate"),
)


class Database:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.engine = create_engine(
            URL.create("sqlite", database=str(self.data_dir / "nexo.sqlite3")),
            connect_args={"check_same_thread": False, "timeout": 0},
            poolclass=NullPool, hide_parameters=True,
        )

        @event.listens_for(self.engine, "connect")
        def configure(connection, _):
            connection.isolation_level = None
            connection.execute("PRAGMA foreign_keys=ON")

        @event.listens_for(self.engine, "begin")
        def begin(connection):
            # Las escrituras adquieren el bloqueo ANTES de consultar/modificar.
            connection.exec_driver_sql(
                "BEGIN IMMEDIATE" if connection.get_execution_options().get("write") else "BEGIN"
            )

    @contextmanager
    def transaction(self, *, write=False):
        with self.engine.connect().execution_options(write=write) as connection:
            with Session(connection, expire_on_commit=False) as session:
                with session.begin():
                    yield session

    def migrate(self, revision="head"):
        self.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        with self.engine.connect().execution_options(write=True) as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, revision)

    def check(self):
        with self.transaction() as session:
            if session.scalar(text("SELECT version_num FROM alembic_version")) != "0002":
                raise RuntimeError("Migraciones pendientes")

    def close(self):
        self.engine.dispose()
