"""Terminales y vinculación; reutiliza las tablas administrativas."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("security_audit", sa.Column("subject_id", sa.String(32)))
    op.create_table(
        "terminals",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("last_activity", sa.Integer, nullable=False),
        sa.Column("revoked_at", sa.Integer),
        sa.Column("voice_config", sa.JSON, nullable=False),
        sa.Column("credential_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.Integer, nullable=False),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 80", name="terminal_name_length"),
        sa.CheckConstraint("length(credential_hash) = 64", name="terminal_digest_length"),
        sa.CheckConstraint("expires_at > created_at", name="terminal_expiry"),
    )
    op.create_table(
        "terminal_permissions",
        sa.Column("terminal_id", sa.String(32), sa.ForeignKey("terminals.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("permission", sa.String(80), primary_key=True),
    )
    op.create_table(
        "pairing_codes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("expires_at", sa.Integer, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("consumed_at", sa.Integer),
        sa.Column("revoked_at", sa.Integer),
        sa.Column("permissions", sa.JSON, nullable=False),
        sa.CheckConstraint("expires_at = created_at + 300", name="pairing_expiry"),
        sa.CheckConstraint("attempts BETWEEN 0 AND 5", name="pairing_attempts"),
        sa.CheckConstraint("length(code_hash) = 64", name="pairing_digest_length"),
    )
    op.create_table(
        "pairing_rate",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("window_start", sa.Integer, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.CheckConstraint("id = 1", name="single_pairing_rate"),
    )
    op.execute(sa.text("INSERT INTO pairing_rate VALUES (1, 0, 0)"))


def downgrade():
    for table in ("pairing_rate", "pairing_codes", "terminal_permissions", "terminals"):
        op.drop_table(table)
    op.drop_column("security_audit", "subject_id")
