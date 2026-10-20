from chat.agents.sql_agent.data_generation.seed_postgres import (
    BENCHMARK_SCHEMA,
    DEFAULT_SEED,
    _synthetic_rows,
    build_benchmark_metadata,
)


def test_benchmark_metadata_builds_one_thousand_unique_tables_and_relationships():
    tables = build_benchmark_metadata(1000)

    assert len(tables) == 1000
    assert len({table.name for table, _ in tables}) == 1000
    assert {table.schema for table, _ in tables} == {BENCHMARK_SCHEMA}
    assert [kind for _, kind in tables].count("fact") == 500
    assert [kind for _, kind in tables].count("dimension") == 200
    assert [kind for _, kind in tables].count("lookup") == 200
    assert [kind for _, kind in tables].count("decoy") == 100
    assert not tables[0][0].foreign_keys
    assert next(iter(tables[1][0].foreign_keys)).target_fullname == (
        f"{BENCHMARK_SCHEMA}.{tables[0][0].name}.id"
    )


def test_synthetic_rows_are_seeded_and_relationships_are_tenant_safe():
    kind = "fact"
    first = list(_synthetic_rows(kind, 15, DEFAULT_SEED, 2))
    second = list(_synthetic_rows(kind, 15, DEFAULT_SEED, 2))

    assert first == second
    assert all(row["tenant_id"] == (row["id"] - 1) % 10 + 1 for row in first)
    assert all(
        row["related_id"] == row["id"]
        and row["tenant_id"] == (row["related_id"] - 1) % 10 + 1
        for row in first
    )
