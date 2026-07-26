"""Group category feeds under publishers.

Revision ID: 20260726_04
Revises: 20260725_03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260726_04"
down_revision: str | None = "20260725_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publishers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("site_url", sa.Text(), unique=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column("sources", sa.Column("publisher_id", sa.BigInteger()))
    op.add_column("sources", sa.Column("category", sa.String(100)))

    op.execute(
        """
        DO $$
        DECLARE
            source_row RECORD;
            selected_publisher_id BIGINT;
        BEGIN
            FOR source_row IN SELECT id, name, site_url FROM sources ORDER BY id LOOP
                selected_publisher_id := NULL;
                IF source_row.site_url IS NOT NULL THEN
                    SELECT id INTO selected_publisher_id
                    FROM publishers
                    WHERE lower(rtrim(site_url, '/')) =
                          lower(rtrim(source_row.site_url, '/'))
                    LIMIT 1;
                END IF;

                IF selected_publisher_id IS NULL THEN
                    INSERT INTO publishers (name, site_url, enabled)
                    VALUES (source_row.name, source_row.site_url, true)
                    RETURNING id INTO selected_publisher_id;
                END IF;

                UPDATE sources
                SET publisher_id = selected_publisher_id
                WHERE id = source_row.id;
            END LOOP;
        END $$;
        """
    )

    op.alter_column("sources", "publisher_id", nullable=False)
    op.create_foreign_key(
        "fk_sources_publisher",
        "sources",
        "publishers",
        ["publisher_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("sources", "site_url")


def downgrade() -> None:
    op.add_column("sources", sa.Column("site_url", sa.Text()))
    op.execute(
        "UPDATE sources SET site_url = publishers.site_url "
        "FROM publishers WHERE publishers.id = sources.publisher_id"
    )
    op.drop_constraint("fk_sources_publisher", "sources", type_="foreignkey")
    op.drop_column("sources", "category")
    op.drop_column("sources", "publisher_id")
    op.drop_table("publishers")
