from datetime import timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import String, func, select, text
from sqlalchemy.orm import Session

from chat.schemas import ChatFilters
from middleware.models import Product, SalesRecord, Site, User


def _scope_filters(db: Session, user: User, filters: ChatFilters) -> list[Any]:
    if filters.site_id is not None:
        site_exists = select(Site.id).where(
            Site.id == filters.site_id, Site.user_id == user.id
        )
        if not db.scalar(site_exists):
            raise HTTPException(status_code=404, detail="Site not found")
    if filters.product_id is not None:
        product_exists = (
            select(Product.id)
            .join(Site, Site.id == Product.site_id)
            .where(Product.id == filters.product_id, Site.user_id == user.id)
        )
        if filters.site_id is not None:
            product_exists = product_exists.where(Product.site_id == filters.site_id)
        if not db.scalar(product_exists):
            raise HTTPException(status_code=404, detail="Product not found")

    clauses: list[Any] = [
        Site.user_id == user.id,
        SalesRecord.sale_date >= filters.start_date,
        SalesRecord.sale_date <= filters.end_date,
    ]
    if filters.site_id is not None:
        clauses.append(SalesRecord.site_id == filters.site_id)
    if filters.product_id is not None:
        clauses.append(SalesRecord.product_id == filters.product_id)
    return clauses


def run_analytics_tool(
    db: Session,
    user: User,
    operation: str,
    metric: str,
    filters: ChatFilters,
) -> dict[str, Any]:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SET LOCAL statement_timeout = '3s'"))
    if operation not in {"overview", "products", "sites", "comparison"}:
        raise ValueError("Unsupported analytics operation")
    if metric not in {"revenue", "units_sold", "orders", "average_order_value"}:
        raise ValueError("Unsupported analytics metric")

    clauses = _scope_filters(db, user, filters)
    if operation == "comparison":
        period_days = (filters.end_date - filters.start_date).days + 1
        previous = ChatFilters(
            site_id=filters.site_id,
            product_id=filters.product_id,
            start_date=filters.start_date - timedelta(days=period_days),
            end_date=filters.start_date - timedelta(days=1),
        )
        previous_result = run_analytics_tool(db, user, "overview", metric, previous)
        current_result = run_analytics_tool(db, user, "overview", metric, filters)
        current = current_result["metrics"][metric]
        earlier = previous_result["metrics"][metric]
        multiple_currencies = (
            metric in {"revenue", "average_order_value"}
            and (
                current_result["multiple_currencies"]
                or previous_result["multiple_currencies"]
            )
        )
        change = (
            ((current - earlier) / abs(earlier) * 100)
            if earlier and not multiple_currencies
            else None
        )
        return {
            "operation": operation,
            "metric": metric,
            "current": current_result,
            "previous": previous_result,
            "change_percent": float(change) if change is not None else None,
            "multiple_currencies": multiple_currencies,
            "filters": filters.model_dump(mode="json"),
            "definition": "Revenue is gross revenue minus discounts; orders are distinct per site.",
        }

    if operation == "overview":
        values = db.execute(
            select(
                func.coalesce(
                    func.sum(SalesRecord.gross_revenue - SalesRecord.discount), 0
                ),
                func.count(func.distinct(Site.id.cast(String) + ":" + SalesRecord.order_id)),
                func.coalesce(func.sum(SalesRecord.quantity), 0),
            )
            .join(Site, Site.id == SalesRecord.site_id)
            .where(*clauses)
        ).one()
        currencies_query = select(Site.currency).where(Site.user_id == user.id)
        if filters.site_id is not None:
            currencies_query = currencies_query.where(Site.id == filters.site_id)
        elif filters.product_id is not None:
            currencies_query = (
                currencies_query.join(Product, Product.site_id == Site.id)
                .where(Product.id == filters.product_id)
            )
        currencies = sorted(set(db.scalars(currencies_query).all()))
        return {
            "operation": operation,
            "metric": metric,
            "metrics": {
                "revenue": float(Decimal(values[0])),
                "orders": int(values[1]),
                "units_sold": int(values[2]),
                "average_order_value": (
                    float(Decimal(values[0]) / int(values[1])) if values[1] else 0.0
                ),
            },
            "currency": currencies[0] if len(currencies) == 1 else None,
            "multiple_currencies": len(currencies) > 1,
            "filters": filters.model_dump(mode="json"),
            "definition": "Net revenue is gross revenue minus discounts; orders are distinct within each site.",
        }

    group_col = Product.id if operation == "products" else Site.id
    name_col = Product.name if operation == "products" else Site.name
    revenue = func.sum(SalesRecord.gross_revenue - SalesRecord.discount)
    units = func.sum(SalesRecord.quantity)
    orders = func.count(func.distinct(Site.id.cast(String) + ":" + SalesRecord.order_id))
    average_order_value = revenue / func.nullif(orders, 0)
    rows = db.execute(
        select(
            group_col,
            name_col,
            Site.currency,
            revenue,
            orders,
            units,
        )
        .join(Site, Site.id == SalesRecord.site_id)
        .join(Product, Product.id == SalesRecord.product_id)
        .where(*clauses)
        .group_by(group_col, name_col, Site.currency)
        .order_by(
            {
                "revenue": revenue.desc(),
                "orders": orders.desc(),
                "units_sold": units.desc(),
                "average_order_value": average_order_value.desc(),
            }[metric]
        )
        .limit(10)
    ).all()
    currencies = {row[2] for row in rows}
    return {
        "operation": operation,
        "metric": metric,
        "multiple_currencies": len(currencies) > 1,
        "rows": [
            {
                "id": row[0],
                "name": row[1],
                "currency": row[2],
                "revenue": float(Decimal(row[3] or 0)),
                "orders": int(row[4] or 0),
                "units_sold": int(row[5] or 0),
                "average_order_value": float(Decimal(row[3] or 0) / int(row[4]))
                if row[4]
                else 0.0,
            }
            for row in rows
        ],
        "filters": filters.model_dump(mode="json"),
        "definition": "Revenue is gross revenue minus discounts; orders are distinct within each site.",
    }
