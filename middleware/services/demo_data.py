from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from middleware.models import Product, SalesRecord, Site, User

DEMO_PERIOD_DAYS = 90
CENT = Decimal("0.01")
SITE_DEFINITIONS = (
    {
        "name": "Northstar Outfitters",
        "slug": "northstar-outfitters",
        "url": "https://northstar.example",
        "products": (
            ("Trail Daypack", "NS-DAYPACK", "Packs", Decimal("78.00")),
            ("Insulated Bottle", "NS-BOTTLE", "Accessories", Decimal("32.00")),
            ("Summit Shell Jacket", "NS-SHELL", "Apparel", Decimal("149.00")),
            ("Merino Hiking Socks", "NS-SOCKS", "Apparel", Decimal("24.00")),
        ),
    },
    {
        "name": "Trail Ready",
        "slug": "trail-ready",
        "url": "https://trail-ready.example",
        "products": (
            ("Trail Daypack", "TR-DAYPACK", "Packs", Decimal("82.00")),
            ("Insulated Bottle", "TR-BOTTLE", "Accessories", Decimal("35.00")),
            ("Summit Shell Jacket", "TR-SHELL", "Apparel", Decimal("155.00")),
            ("Merino Hiking Socks", "TR-SOCKS", "Apparel", Decimal("26.00")),
        ),
    },
)


def seed_demo_data(db: Session, user: User, *, today: date | None = None) -> int:
    """Insert missing deterministic demo sites, products, and orders for a user."""
    today = today or date.today()
    demo_slugs = [item["slug"] for item in SITE_DEFINITIONS]
    sites = {
        site.slug: site
        for site in db.scalars(
            select(Site).where(Site.user_id == user.id, Site.slug.in_(demo_slugs))
        ).all()
    }

    for definition in SITE_DEFINITIONS:
        if definition["slug"] not in sites:
            site = Site(
                user_id=user.id,
                name=definition["name"],
                slug=definition["slug"],
                url=definition["url"],
                currency="USD",
                is_demo=True,
            )
            db.add(site)
            sites[definition["slug"]] = site
    db.flush()

    site_ids = [site.id for site in sites.values()]
    products_by_site: dict[int, dict[str, Product]] = {}
    for site in db.scalars(select(Site).where(Site.id.in_(site_ids))).all():
        products_by_site[site.id] = {
            product.sku: product
            for product in db.scalars(
                select(Product).where(Product.site_id == site.id)
            ).all()
        }

    definitions_by_slug = {item["slug"]: item for item in SITE_DEFINITIONS}
    for slug, site in sites.items():
        for name, sku, category, price in definitions_by_slug[slug]["products"]:
            if sku not in products_by_site[site.id]:
                product = Product(
                    site_id=site.id,
                    name=name,
                    sku=sku,
                    category=category,
                    unit_price=price,
                )
                db.add(product)
                products_by_site[site.id][sku] = product
    db.flush()

    pending_records: list[SalesRecord] = []
    candidate_order_ids: list[str] = []
    for site_index, definition in enumerate(SITE_DEFINITIONS):
        site = sites[definition["slug"]]
        products = products_by_site[site.id]
        product_skus = [item[1] for item in definition["products"]]
        for day_offset in range(DEMO_PERIOD_DAYS):
            sale_date = today - timedelta(days=day_offset)
            daily_orders = 2 + ((day_offset * 7 + site_index * 3) % 5)
            weekday_lift = 1 if sale_date.weekday() in (4, 5) else 0
            for order_index in range(daily_orders + weekday_lift):
                order_id = (
                    f"demo-{definition['slug']}-{sale_date.isoformat()}-"
                    f"{order_index:02d}"
                )
                candidate_order_ids.append(order_id)
                product_sku = product_skus[
                    (day_offset * 3 + order_index * 2 + site_index) % len(product_skus)
                ]
                price = next(
                    product[3]
                    for product in definition["products"]
                    if product[1] == product_sku
                )
                quantity = 1 + ((day_offset + order_index + site_index) % 3 == 0)
                gross = (price * quantity).quantize(CENT, rounding=ROUND_HALF_UP)
                discount = (
                    (gross * Decimal("0.05")).quantize(CENT, rounding=ROUND_HALF_UP)
                    if (day_offset + order_index) % 7 == 0
                    else Decimal("0.00")
                )
                pending_records.append(
                    SalesRecord(
                        site_id=site.id,
                        product_id=products[product_sku].id,
                        order_id=order_id,
                        sale_date=sale_date,
                        quantity=int(quantity),
                        gross_revenue=gross,
                        discount=discount,
                    )
                )

    existing_order_ids = set(
        db.scalars(
            select(SalesRecord.order_id).where(
                SalesRecord.site_id.in_(site_ids),
                SalesRecord.order_id.in_(candidate_order_ids),
            )
        ).all()
    )
    new_records = [
        record for record in pending_records if record.order_id not in existing_order_ids
    ]
    db.add_all(new_records)
    return len(new_records)
