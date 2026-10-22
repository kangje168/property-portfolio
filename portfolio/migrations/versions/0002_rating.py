"""Add bounded rating and per-manager name/address uniqueness."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = depends_on = None


def upgrade():
    # A duplicate in an existing database must be reconciled by its operator.
    # Fail rather than silently deleting rows during the migration.
    with op.batch_alter_table("properties") as batch:
        batch.add_column(sa.Column("rating", sa.Integer, nullable=True))
        batch.create_check_constraint("ck_rating", "rating BETWEEN 1 AND 5")
        batch.create_unique_constraint(
            "uq_property_address", ["manager_id", "name", "address"]
        )


def downgrade():
    with op.batch_alter_table("properties") as batch:
        batch.drop_constraint("uq_property_address", type_="unique")
        batch.drop_constraint("ck_rating", type_="check")
        batch.drop_column("rating")
