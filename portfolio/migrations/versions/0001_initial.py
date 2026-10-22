"""Create the initial portfolio schema; rating follows in a real migration."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "managers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
    )
    op.create_table(
        "properties",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "manager_id", sa.Integer, sa.ForeignKey("managers.id"), nullable=False
        ),
        sa.Column("external_id", sa.String(80), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("address", sa.String(240), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("property_type", sa.String(20), nullable=False),
        sa.Column("bedrooms", sa.Integer, nullable=False),
        sa.Column("price_cents", sa.BigInteger, nullable=False),
        sa.Column("latitude", sa.Float, nullable=False),
        sa.Column("longitude", sa.Float, nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("manager_id", "external_id", name="uq_property_external"),
        sa.CheckConstraint("bedrooms BETWEEN 0 AND 20", name="ck_bedrooms"),
        sa.CheckConstraint(
            "price_cents >= 0 AND price_cents <= 100000000000", name="ck_price"
        ),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_latitude"),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_longitude"),
        sa.CheckConstraint(
            "property_type IN ('apartment', 'house', 'office', 'retail')",
            name="ck_type",
        ),
    )
    op.create_index("ix_properties_manager_id", "properties", ["manager_id"])
    op.create_index(
        "ix_property_search",
        "properties",
        ["manager_id", "property_type", "price_cents"],
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("digest", sa.String(64), nullable=False, unique=True),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column(
            "manager_id", sa.Integer, sa.ForeignKey("managers.id"), nullable=True
        ),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("expires_at", sa.String(40), nullable=False),
        sa.Column("revoked", sa.Boolean, nullable=False),
        sa.CheckConstraint(
            "role IN ('admin', 'manager', 'reader')", name="ck_key_role"
        ),
        sa.CheckConstraint(
            "role = 'admin' OR manager_id IS NOT NULL", name="ck_key_scope"
        ),
    )
    op.create_table(
        "imports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "manager_id", sa.Integer, sa.ForeignKey("managers.id"), nullable=False
        ),
        sa.Column("key_id", sa.Integer, sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("report", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "audit",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key_id", sa.Integer, sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("resource_id", sa.Integer, nullable=False),
        sa.Column("details", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "rate_buckets",
        sa.Column("key_id", sa.Integer, sa.ForeignKey("api_keys.id"), primary_key=True),
        sa.Column("window", sa.Integer, primary_key=True),
        sa.Column("count", sa.Integer, nullable=False),
    )


def downgrade():
    for name in [
        "rate_buckets",
        "audit",
        "imports",
        "api_keys",
        "properties",
        "managers",
    ]:
        op.drop_table(name)
