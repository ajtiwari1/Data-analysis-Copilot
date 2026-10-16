"""Add per-user sites, products, and demo sales records.

Revision ID: 0002_sales_analytics
Revises: 0001_auth_tables
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_sales_analytics"
down_revision = "0001_auth_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("url", sa.String(length=255), nullable=False),
        sa.Column(
            "currency", sa.String(length=3), nullable=False, server_default="USD"
        ),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "slug", name="uq_sites_user_slug"),
    )
    op.create_index("ix_sites_user_id", "sites", ["user_id"], unique=False)

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "site_id",
            sa.Integer(),
            sa.ForeignKey("sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("sku", sa.String(length=80), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.UniqueConstraint("site_id", "sku", name="uq_products_site_sku"),
        sa.UniqueConstraint("site_id", "id", name="uq_products_site_id"),
    )
    op.create_index("ix_products_site_id", "products", ["site_id"], unique=False)

    op.create_table(
        "sales_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "site_id",
            sa.Integer(),
            sa.ForeignKey("sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.String(length=100), nullable=False),
        sa.Column("sale_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("gross_revenue", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "discount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
        sa.ForeignKeyConstraint(
            ["site_id", "product_id"],
            ["products.site_id", "products.id"],
            name="fk_sales_product_site",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "site_id", "order_id", "product_id", name="uq_sales_site_order_product"
        ),
    )
    op.create_index(
        "ix_sales_records_site_id", "sales_records", ["site_id"], unique=False
    )
    op.create_index(
        "ix_sales_records_product_id", "sales_records", ["product_id"], unique=False
    )
    op.create_index(
        "ix_sales_records_sale_date", "sales_records", ["sale_date"], unique=False
    )
    op.create_index(
        "ix_sales_site_date",
        "sales_records",
        ["site_id", "sale_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sales_site_date", table_name="sales_records")
    op.drop_index("ix_sales_records_sale_date", table_name="sales_records")
    op.drop_index("ix_sales_records_product_id", table_name="sales_records")
    op.drop_index("ix_sales_records_site_id", table_name="sales_records")
    op.drop_table("sales_records")
    op.drop_index("ix_products_site_id", table_name="products")
    op.drop_table("products")
    op.drop_index("ix_sites_user_id", table_name="sites")
    op.drop_table("sites")
