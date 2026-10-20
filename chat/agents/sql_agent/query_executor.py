from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from typing import Any

import sqlglot
from sqlglot import exp
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from chat.agents.sql_agent.schemas import SQLAgentError
from chat.schemas import ChatFilters
from middleware.models import User

MAX_SQL_LENGTH = 4000
MAX_RESULT_ROWS = 100
MAX_RESULT_COLUMNS = 20
MAX_RESULT_BYTES = 48_000
ALLOWED_TABLES = {"products", "sales_records", "sites"}
ALLOWED_COLUMNS = {
    "products": {"id", "name", "sku", "category", "unit_price", "site_id"},
    "sales_records": {
        "id",
        "site_id",
        "product_id",
        "order_id",
        "sale_date",
        "quantity",
        "gross_revenue",
        "discount",
    },
    "sites": {"id", "name", "currency"},
}
ALLOWED_FUNCTIONS = {
    "AVG",
    "COALESCE",
    "COUNT",
    "MAX",
    "MIN",
    "ROUND",
    "SUM",
}
ALLOWED_LOGICAL_NODES = (exp.And, exp.Or, exp.Not)


def _invalid_sql() -> SQLAgentError:
    return SQLAgentError(
        "The generated SQL did not pass the read-only analytics safety checks. Please rephrase your question."
    )


def validate_and_scope_sql(sql: str, filters: ChatFilters) -> tuple[str, dict[str, Any]]:
    if not sql.strip() or len(sql) > MAX_SQL_LENGTH:
        raise _invalid_sql()

    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.SqlglotError as error:
        raise _invalid_sql() from error
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise _invalid_sql()

    query = statements[0]
    if any(
        query.find(node_type) is not None
        for node_type in (
            exp.Subquery,
            exp.CTE,
            exp.Into,
            exp.Lateral,
            exp.Lock,
            exp.Placeholder,
            exp.Window,
        )
    ):
        raise _invalid_sql()

    tables = list(query.find_all(exp.Table))
    table_names: set[str] = set()
    for table in tables:
        name = table.name.lower()
        if (
            name not in ALLOWED_TABLES
            or table.alias
            or table.db
            or table.catalog
        ):
            raise _invalid_sql()
        table_names.add(name)
    if not {"sales_records", "sites"}.issubset(table_names):
        raise _invalid_sql()

    for column in query.find_all(exp.Column):
        table_name = column.table.lower()
        if (
            table_name not in table_names
            or column.name.lower() not in ALLOWED_COLUMNS[table_name]
            or column.db
            or column.catalog
        ):
            raise _invalid_sql()
    for star in query.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            raise _invalid_sql()
    for function in query.find_all(exp.Func):
        if (
            function.sql_name().upper() not in ALLOWED_FUNCTIONS
            and not isinstance(function, ALLOWED_LOGICAL_NODES)
        ):
            raise _invalid_sql()
    if any(node.comments for node in query.walk()):
        raise _invalid_sql()

    for projection in query.expressions:
        count = projection.find(exp.Count)
        count_star = count is not None and isinstance(count.this, exp.Star)
        if not list(projection.find_all(exp.Column)) and not count_star:
            raise _invalid_sql()
    if len(query.expressions) > MAX_RESULT_COLUMNS:
        raise _invalid_sql()
    if query.args.get("offset") is not None or query.args.get("locks"):
        raise _invalid_sql()

    limit = query.args.get("limit")
    if limit is not None:
        limit_value = limit.expression
        if not isinstance(limit_value, exp.Literal) or not limit_value.is_int:
            raise _invalid_sql()
        limit.set(
            "expression",
            exp.Literal.number(min(int(limit_value.this), MAX_RESULT_ROWS)),
        )
    else:
        query.set(
            "limit",
            exp.Limit(expression=exp.Literal.number(MAX_RESULT_ROWS)),
        )

    required_predicates = [
        "sites.user_id = :authenticated_user_id",
        "sales_records.site_id = sites.id",
        "sales_records.sale_date >= :start_date",
        "sales_records.sale_date <= :end_date",
    ]
    parameters: dict[str, Any] = {
        "authenticated_user_id": None,
        "start_date": filters.start_date,
        "end_date": filters.end_date,
    }
    if filters.site_id is not None:
        required_predicates.append("sites.id = :selected_site_id")
        parameters["selected_site_id"] = filters.site_id
    if filters.product_id is not None:
        required_predicates.append("sales_records.product_id = :selected_product_id")
        parameters["selected_product_id"] = filters.product_id
    if "products" in table_names:
        required_predicates.extend(
            [
                "products.id = sales_records.product_id",
                "products.site_id = sites.id",
            ]
        )

    policy = sqlglot.parse_one(
        " AND ".join(required_predicates),
        read="postgres",
        into=exp.Condition,
    )
    existing_where = query.args.get("where")
    if existing_where is not None:
        policy = exp.and_(policy, existing_where.this)
    query.set("where", exp.Where(this=policy))

    safe_sql = query.sql()
    return safe_sql, parameters


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def execute_scoped_sql(
    db: Session,
    user: User,
    filters: ChatFilters,
    generated_sql: str,
) -> dict[str, Any]:
    safe_sql, parameters = validate_and_scope_sql(generated_sql, filters)
    parameters["authenticated_user_id"] = user.id
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SET LOCAL statement_timeout = '3s'"))
    try:
        result = db.execute(text(safe_sql), parameters)
        columns = list(result.keys())
        rows = result.mappings().all()
    except SQLAlchemyError as error:
        raise SQLAgentError(
            "The generated analytics query could not be executed safely."
        ) from error

    data = [
        {key: _json_value(value) for key, value in row.items()}
        for row in rows[:MAX_RESULT_ROWS]
    ]
    serialized = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > MAX_RESULT_BYTES:
        raise SQLAgentError(
            "The query returned too much data to summarize. Please narrow your filters."
        )
    return {
        "columns": columns,
        "rows": data,
        "row_count": len(data),
        "sql_fingerprint": hashlib.sha256(safe_sql.encode("utf-8")).hexdigest(),
        "filters": filters.model_dump(mode="json"),
    }
