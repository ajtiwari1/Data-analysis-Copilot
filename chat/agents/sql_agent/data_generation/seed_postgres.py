"""Create a deterministic synthetic 1,000-table PostgreSQL benchmark schema."""

import argparse
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import os
import random

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    MetaData,
    Numeric,
    String,
    Table,
    create_engine,
    inspect,
)
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.schema import CreateSchema, DropSchema

BENCHMARK_SCHEMA = "sql_agent_bench"
DEFAULT_TABLE_COUNT = 1000
DEFAULT_ROWS_PER_TABLE = 25
DEFAULT_SEED = 20261017
MAX_TABLE_COUNT = 5000
MAX_ROWS_PER_TABLE = 1000
MAX_TOTAL_ROWS = 1_000_000
INSERT_BATCH_SIZE = 500
BASE_DATE = date(2020, 1, 1)
DOMAINS = (
    "sales",
    "marketing",
    "finance",
    "operations",
    "support",
    "logistics",
    "product",
    "web",
    "security",
    "billing",
    "inventory",
    "growth",
    "orders",
    "returns",
    "shipping",
    "accounts",
    "campaigns",
    "customers",
    "devices",
    "subscriptions",
)
TABLE_KIND_CYCLE = (
    "fact",
    "fact",
    "fact",
    "fact",
    "fact",
    "dimension",
    "dimension",
    "lookup",
    "lookup",
    "decoy",
)
CATEGORIES = ("standard", "premium", "seasonal", "clearance", "unknown")


def _table_kind(index: int) -> str:
    return TABLE_KIND_CYCLE[(index - 1) % len(TABLE_KIND_CYCLE)]


def build_benchmark_metadata(table_count: int) -> list[tuple[Table, str]]:
    if not 1 <= table_count <= MAX_TABLE_COUNT:
        raise ValueError(f"table_count must be between 1 and {MAX_TABLE_COUNT}")

    metadata = MetaData(schema=BENCHMARK_SCHEMA)
    tables: list[tuple[Table, str]] = []
    previous_table_name: str | None = None
    for index in range(1, table_count + 1):
        kind = _table_kind(index)
        domain = DOMAINS[(index - 1) % len(DOMAINS)]
        table_name = f"bench_{domain}_{kind}_{index:04d}"
        columns = [
            Column("id", Integer, primary_key=True),
            Column("tenant_id", Integer, nullable=False),
            Column(
                "related_id",
                Integer,
                ForeignKey(
                    f"{BENCHMARK_SCHEMA}.{previous_table_name}.id",
                    ondelete="SET NULL",
                )
                if previous_table_name
                else None,
                nullable=True,
            ),
        ]
        if kind == "fact":
            columns.extend(
                [
                    Column("event_date", Date, nullable=False),
                    Column("metric_value", Numeric(14, 2), nullable=False),
                    Column("quantity", Integer, nullable=False),
                    Column("category", String(40), nullable=False),
                ]
            )
        elif kind == "dimension":
            columns.extend(
                [
                    Column("name", String(120), nullable=False),
                    Column("category", String(40), nullable=False),
                    Column("is_active", Boolean, nullable=False),
                ]
            )
        elif kind == "lookup":
            columns.extend(
                [
                    Column("code", String(40), nullable=False),
                    Column("label", String(120), nullable=False),
                    Column("category", String(40), nullable=False),
                ]
            )
        else:
            columns.extend(
                [
                    Column("observed_at", DateTime(timezone=True), nullable=False),
                    Column("note", String(160), nullable=False),
                    Column("attributes", JSON, nullable=False),
                ]
            )

        table = Table(table_name, metadata, *columns)
        tables.append((table, kind))
        previous_table_name = table_name
    return tables


def _synthetic_rows(
    kind: str,
    row_count: int,
    seed: int,
    table_index: int,
) -> Iterator[dict[str, object]]:
    rng = random.Random(seed + table_index * 1_000_003)
    category_offset = rng.randrange(len(CATEGORIES))
    for row_id in range(1, row_count + 1):
        tenant_id = (row_id - 1) % 10 + 1
        related_id = row_id if table_index > 1 else None
        category = CATEGORIES[(row_id + category_offset) % len(CATEGORIES)]
        if kind == "fact":
            yield {
                "id": row_id,
                "tenant_id": tenant_id,
                "related_id": related_id,
                "event_date": BASE_DATE + timedelta(days=rng.randrange(2400)),
                "metric_value": Decimal(rng.randrange(0, 1_000_000)) / Decimal(100),
                "quantity": rng.choices((1, 2, 3, 5, 10), weights=(55, 22, 12, 8, 3))[0],
                "category": category,
            }
        elif kind == "dimension":
            yield {
                "id": row_id,
                "tenant_id": tenant_id,
                "related_id": related_id,
                "name": f"synthetic-{table_index:04d}-{row_id:06d}",
                "category": category,
                "is_active": rng.random() >= 0.1,
            }
        elif kind == "lookup":
            yield {
                "id": row_id,
                "tenant_id": tenant_id,
                "related_id": related_id,
                "code": f"CODE-{table_index:04d}-{row_id:06d}",
                "label": f"Synthetic label {row_id:06d}",
                "category": category,
            }
        else:
            observed_at = datetime.combine(
                BASE_DATE + timedelta(days=rng.randrange(2400)),
                time(hour=rng.randrange(24), minute=rng.randrange(60)),
                tzinfo=timezone.utc,
            )
            yield {
                "id": row_id,
                "tenant_id": tenant_id,
                "related_id": related_id,
                "observed_at": observed_at,
                "note": f"Synthetic decoy event {row_id:06d}",
                "attributes": {
                    "source": "sql-agent-benchmark",
                    "category": category,
                    "nullable_sample": None if rng.random() < 0.2 else "synthetic",
                },
            }


def _insert_table_rows(
    connection: Connection,
    table: Table,
    kind: str,
    row_count: int,
    seed: int,
    table_index: int,
) -> None:
    rows = _synthetic_rows(kind, row_count, seed, table_index)
    while batch := list(_take(rows, INSERT_BATCH_SIZE)):
        connection.execute(table.insert(), batch)


def _take(
    rows: Iterator[dict[str, object]], count: int
) -> Iterator[dict[str, object]]:
    for _ in range(count):
        try:
            yield next(rows)
        except StopIteration:
            return


def seed_benchmark(
    engine: Engine,
    *,
    table_count: int = DEFAULT_TABLE_COUNT,
    rows_per_table: int = DEFAULT_ROWS_PER_TABLE,
    seed: int = DEFAULT_SEED,
    reset: bool = False,
) -> int:
    if not 1 <= rows_per_table <= MAX_ROWS_PER_TABLE:
        raise ValueError(
            f"rows_per_table must be between 1 and {MAX_ROWS_PER_TABLE}"
        )
    if table_count * rows_per_table > MAX_TOTAL_ROWS:
        raise ValueError(f"Total rows cannot exceed {MAX_TOTAL_ROWS}")

    tables = build_benchmark_metadata(table_count)
    with engine.begin() as connection:
        schema_exists = inspect(connection).has_schema(BENCHMARK_SCHEMA)
        if schema_exists and not reset:
            raise RuntimeError(
                f"Schema {BENCHMARK_SCHEMA!r} already exists; pass --reset to replace "
                "only this synthetic benchmark schema."
            )
        if schema_exists:
            connection.execute(DropSchema(BENCHMARK_SCHEMA, cascade=True))
        connection.execute(CreateSchema(BENCHMARK_SCHEMA))
        metadata = tables[0][0].metadata
        metadata.create_all(connection)
        for index, (table, kind) in enumerate(tables, start=1):
            _insert_table_rows(
                connection, table, kind, rows_per_table, seed, index
            )
    return table_count * rows_per_table


def drop_benchmark(engine: Engine) -> bool:
    with engine.begin() as connection:
        if not inspect(connection).has_schema(BENCHMARK_SCHEMA):
            return False
        connection.execute(DropSchema(BENCHMARK_SCHEMA, cascade=True))
    return True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create or drop deterministic synthetic SQL-agent benchmark tables in "
            f"the dedicated PostgreSQL schema {BENCHMARK_SCHEMA!r}."
        )
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("SQL_AGENT_BENCH_DATABASE_URL"),
        help=(
            "PostgreSQL SQLAlchemy URL. Defaults to SQL_AGENT_BENCH_DATABASE_URL; "
            "does not use the application's DATABASE_URL."
        ),
    )
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument(
        "--reset",
        action="store_true",
        help=f"Drop and recreate only the dedicated {BENCHMARK_SCHEMA!r} schema.",
    )
    operation.add_argument(
        "--drop",
        action="store_true",
        help=f"Drop only the dedicated {BENCHMARK_SCHEMA!r} schema and exit.",
    )
    parser.add_argument(
        "--tables",
        type=int,
        default=DEFAULT_TABLE_COUNT,
        help=f"Number of synthetic tables (default: {DEFAULT_TABLE_COUNT}; max: {MAX_TABLE_COUNT}).",
    )
    parser.add_argument(
        "--rows-per-table",
        type=int,
        default=DEFAULT_ROWS_PER_TABLE,
        help=(
            f"Rows per table (default: {DEFAULT_ROWS_PER_TABLE}; max: "
            f"{MAX_ROWS_PER_TABLE}; total max: {MAX_TOTAL_ROWS})."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Reproducible synthetic-data seed (default: {DEFAULT_SEED}).",
    )
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    if not args.database_url:
        parser.error(
            "Provide --database-url or set SQL_AGENT_BENCH_DATABASE_URL. "
            "The application database setting is intentionally not used."
        )
    try:
        database_url = make_url(args.database_url)
    except (TypeError, ValueError) as error:
        parser.error(f"Invalid PostgreSQL database URL: {error}")
    if not database_url.drivername.startswith("postgresql"):
        parser.error("The benchmark generator requires a PostgreSQL database URL.")
    if not args.drop and not 1 <= args.tables <= MAX_TABLE_COUNT:
        parser.error(f"--tables must be between 1 and {MAX_TABLE_COUNT}.")
    if not args.drop and not 1 <= args.rows_per_table <= MAX_ROWS_PER_TABLE:
        parser.error(f"--rows-per-table must be between 1 and {MAX_ROWS_PER_TABLE}.")
    if (
        not args.drop
        and args.tables * args.rows_per_table > MAX_TOTAL_ROWS
    ):
        parser.error(f"Total generated rows cannot exceed {MAX_TOTAL_ROWS}.")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        if args.drop:
            dropped = drop_benchmark(engine)
            print(
                f"{'Dropped' if dropped else 'No benchmark schema found:'} "
                f"{BENCHMARK_SCHEMA}."
            )
            return
        inserted_rows = seed_benchmark(
            engine,
            table_count=args.tables,
            rows_per_table=args.rows_per_table,
            seed=args.seed,
            reset=args.reset,
        )
    finally:
        engine.dispose()

    print(
        f"Created {args.tables} synthetic tables in schema {BENCHMARK_SCHEMA} "
        f"with {inserted_rows} rows (seed={args.seed})."
    )


if __name__ == "__main__":
    main()
