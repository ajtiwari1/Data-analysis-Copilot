from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import cast, func, literal, select, String
from sqlalchemy.orm import Session

from middleware.dependencies import CurrentUser, DbSession
from middleware.models import Product, SalesRecord, Site, User
from middleware.schemas import (
    AnalyticsOverviewResponse,
    DailySalesResponse,
    ProductSalesResponse,
    ProductResponse,
    SiteResponse,
)

router = APIRouter(prefix="/analytics")


@router.get("/sites", response_model=list[SiteResponse])
def list_sites(user: CurrentUser, db: DbSession) -> list[Site]:
    return list(
        db.scalars(
            select(Site).where(Site.user_id == user.id).order_by(Site.name)
        ).all()
    )


@router.get("/products", response_model=list[ProductResponse])
def list_products(
    user: CurrentUser,
    db: DbSession,
    site_id: int | None = Query(default=None, gt=0),
) -> list[Product]:
    query = (
        select(Product)
        .join(Site, Site.id == Product.site_id)
        .where(Site.user_id == user.id)
        .order_by(Product.name)
    )
    if site_id is not None:
        _owned_site(db, user, site_id)
        query = query.where(Product.site_id == site_id)
    return list(db.scalars(query).all())


def _owned_site(db: Session, user: User, site_id: int) -> Site:
    site = db.scalar(
        select(Site).where(Site.id == site_id, Site.user_id == user.id)
    )
    if site is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Site not found"
        )
    return site


def _owned_product(
    db: Session, user: User, product_id: int, site_id: int | None
) -> Product:
    query = (
        select(Product)
        .join(Site, Site.id == Product.site_id)
        .where(Product.id == product_id, Site.user_id == user.id)
    )
    if site_id is not None:
        query = query.where(Product.site_id == site_id)
    product = db.scalar(query)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )
    return product


def _summary(
    db: Session,
    user: User,
    start_date: date,
    end_date: date,
    site_id: int | None,
    product_id: int | None,
) -> tuple[Decimal, int, int, str]:
    filters = [
        Site.user_id == user.id,
        SalesRecord.sale_date >= start_date,
        SalesRecord.sale_date <= end_date,
    ]
    if site_id is not None:
        filters.append(SalesRecord.site_id == site_id)
    if product_id is not None:
        filters.append(SalesRecord.product_id == product_id)

    distinct_order_id = cast(Site.id, String) + literal(":") + SalesRecord.order_id
    query = (
        select(
            func.coalesce(
                func.sum(SalesRecord.gross_revenue - SalesRecord.discount), 0
            ),
            func.count(func.distinct(distinct_order_id)),
            func.coalesce(func.sum(SalesRecord.quantity), 0),
        )
        .join(Site, Site.id == SalesRecord.site_id)
        .where(*filters)
    )
    revenue, orders, units_sold = db.execute(query).one()
    currency_query = select(Site.currency).where(Site.user_id == user.id)
    if site_id is not None:
        currency_query = currency_query.where(Site.id == site_id)
    currencies = set(db.scalars(currency_query).all())
    if product_id is not None and site_id is None:
        product = db.get(Product, product_id)
        if product is not None:
            site = db.get(Site, product.site_id)
            if site is not None:
                currencies = {site.currency}
    if len(currencies) > 1:
        raise HTTPException(
            status_code=422,
            detail="Select a single-currency site to view combined revenue",
        )
    return Decimal(revenue), int(orders), int(units_sold), next(iter(currencies), "USD")


@router.get("/overview", response_model=AnalyticsOverviewResponse)
def get_overview(
    user: CurrentUser,
    db: DbSession,
    site_id: int | None = Query(default=None, gt=0),
    product_id: int | None = Query(default=None, gt=0),
    start_date: date | None = None,
    end_date: date | None = None,
) -> AnalyticsOverviewResponse:
    end = end_date or date.today()
    start = start_date or end - timedelta(days=29)
    if start > end:
        raise HTTPException(
            status_code=422,
            detail="start_date must be on or before end_date",
        )
    if site_id is not None:
        _owned_site(db, user, site_id)
    if product_id is not None:
        _owned_product(db, user, product_id, site_id)

    revenue, orders, units_sold, currency = _summary(
        db, user, start, end, site_id, product_id
    )

    filters = [
        Site.user_id == user.id,
        SalesRecord.sale_date >= start,
        SalesRecord.sale_date <= end,
    ]
    if site_id is not None:
        filters.append(SalesRecord.site_id == site_id)
    if product_id is not None:
        filters.append(SalesRecord.product_id == product_id)

    daily_rows = db.execute(
        select(
            SalesRecord.sale_date,
            func.sum(SalesRecord.gross_revenue - SalesRecord.discount),
            func.count(
                func.distinct(
                    cast(Site.id, String) + literal(":") + SalesRecord.order_id
                )
            ),
            func.sum(SalesRecord.quantity),
        )
        .join(Site, Site.id == SalesRecord.site_id)
        .where(*filters)
        .group_by(SalesRecord.sale_date)
        .order_by(SalesRecord.sale_date)
    ).all()
    daily_by_date = {
        row[0]: (Decimal(row[1]), int(row[2]), int(row[3])) for row in daily_rows
    }
    daily_sales = []
    current = start
    while current <= end:
        day_revenue, day_orders, day_units = daily_by_date.get(
            current, (Decimal("0"), 0, 0)
        )
        daily_sales.append(
            DailySalesResponse(
                date=current,
                revenue=float(day_revenue),
                orders=day_orders,
                units_sold=day_units,
            )
        )
        current += timedelta(days=1)

    product_rows = db.execute(
        select(
            Product.id,
            Product.name,
            Product.sku,
            func.sum(SalesRecord.gross_revenue - SalesRecord.discount),
            func.count(func.distinct(SalesRecord.order_id)),
            func.sum(SalesRecord.quantity),
        )
        .join(SalesRecord, SalesRecord.product_id == Product.id)
        .join(Site, Site.id == SalesRecord.site_id)
        .where(*filters)
        .group_by(Product.id, Product.name, Product.sku)
        .order_by(func.sum(SalesRecord.gross_revenue - SalesRecord.discount).desc())
    ).all()
    product_sales = [
        ProductSalesResponse(
            product_id=row[0],
            name=row[1],
            sku=row[2],
            revenue=float(row[3]),
            orders=int(row[4]),
            units_sold=int(row[5]),
        )
        for row in product_rows
    ]

    return AnalyticsOverviewResponse(
        start_date=start,
        end_date=end,
        currency=currency,
        revenue=float(revenue),
        orders=orders,
        units_sold=units_sold,
        average_order_value=float(revenue / orders) if orders else 0.0,
        daily_sales=daily_sales,
        product_sales=product_sales,
    )
