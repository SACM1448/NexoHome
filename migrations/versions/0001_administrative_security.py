"""Persistencia administrativa inicial, sin tablas de futuras entregas."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "administrators",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("active", sa.Boolean(create_constraint=True), nullable=False),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.Integer, nullable=False),
        sa.CheckConstraint("id = 1", name="single_principal"),
        sa.CheckConstraint("length(username) BETWEEN 3 AND 64", name="username_length"),
    )
    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("administrator_id", sa.Integer, sa.ForeignKey("administrators.id"), nullable=False),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("expires_at", sa.Integer, nullable=False),
        sa.Column("revoked", sa.Boolean(create_constraint=True), nullable=False),
        sa.CheckConstraint("expires_at = created_at + 3600", name="absolute_expiry"),
        sa.CheckConstraint("length(token_hash) = 64", name="token_hash_length"),
    )
    op.create_index("single_active_session", "admin_sessions", ["administrator_id"],
                    unique=True, sqlite_where=sa.text("revoked = 0"))
    op.create_table(
        "security_audit",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("occurred_at", sa.Integer, nullable=False),
        sa.Column("event", sa.String(40), nullable=False),
        sa.Column("administrator_id", sa.Integer, sa.ForeignKey("administrators.id")),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(40)),
    )
    op.create_index("ix_security_audit_occurred_at", "security_audit", ["occurred_at"])
    op.create_index("ix_security_audit_event", "security_audit", ["event"])


def downgrade():
    op.drop_table("security_audit")
    op.drop_table("admin_sessions")
    op.drop_table("administrators")
