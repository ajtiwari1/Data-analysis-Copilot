import asyncio
from datetime import date, timedelta
import json
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from chat.models import ChatConversation, ChatMessage
from chat.agents.sql_agent import SQLAgent, SQLAgentError
from chat.agents.sql_agent.mcp_server import create_sql_agent_mcp_server
from chat.agents.sql_agent.query_executor import (
    validate_and_scope_sql,
)
from chat.schemas import ChatFilters
from chat.services.analytics import run_analytics_tool
from chat.utils.llm_factory import (
    LLMConfig,
    LLMProviderError,
    create_llm_client,
)
from middleware.config import settings
from middleware.database import Base, get_db
from middleware.main import app
from middleware.models import AuthSession, User
from mcp.shared.memory import create_connected_server_and_client_session


@pytest.fixture
def chat_client(monkeypatch: pytest.MonkeyPatch):
    test_database_url = os.getenv("TEST_DATABASE_URL")
    if test_database_url:
        engine = create_engine(test_database_url, pool_pre_ping=True)
        with sessionmaker(bind=engine)() as db:
            db.execute(delete(AuthSession))
            db.execute(delete(User))
            db.commit()
    else:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)

    testing_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        with testing_session() as db:
            yield db

    monkeypatch.setattr(settings, "session_cookie_secure", False)
    monkeypatch.setattr(settings, "frontend_origin", "http://testserver")
    monkeypatch.setattr("chat.routes.chat.SessionLocal", testing_session)
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, testing_session
    app.dependency_overrides.clear()
    if not test_database_url:
        Base.metadata.drop_all(engine)
    engine.dispose()


def register(client: TestClient, email: str) -> int:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "a-very-long-password"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_chat_conversation_ownership_and_delete(chat_client):
    client, session_factory = chat_client
    first_user_id = register(client, "chat-first@example.com")
    first_cookie = client.cookies.get("mic_session")
    created = client.post(
        "/api/chat/conversations", json={"title": "Sales questions"}
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]
    assert client.get("/api/chat/conversations").json()[0]["id"] == conversation_id

    second_user_id = register(client, "chat-second@example.com")
    assert second_user_id != first_user_id
    assert client.get("/api/chat/conversations").json() == []
    assert (
        client.get(
            f"/api/chat/conversations/{conversation_id}/messages"
        ).status_code
        == 404
    )

    client.cookies.set("mic_session", first_cookie)
    assert client.delete(f"/api/chat/conversations/{conversation_id}").status_code == 204
    with session_factory() as db:
        assert db.get(ChatConversation, conversation_id) is None


def test_chat_routes_require_authentication(chat_client):
    client, _ = chat_client
    assert client.get("/api/chat/conversations").status_code == 401
    assert (
        client.post("/api/chat/conversations", json={}).status_code == 401
    )


def test_chat_websocket_persists_messages_and_uses_grounded_data(
    chat_client, monkeypatch: pytest.MonkeyPatch
):
    client, session_factory = chat_client
    user_id = register(client, "chat-websocket@example.com")
    conversation_id = client.post("/api/chat/conversations", json={}).json()["id"]
    site_id = client.get("/api/analytics/sites").json()[0]["id"]

    class FakeLLM:
        async def complete(self, messages: list[dict[str, str]]) -> str:
            if "generate one read-only PostgreSQL SELECT" in messages[0]["content"]:
                assert "sales_records" in messages[0]["content"]
                assert "sql_agent_bench" not in messages[0]["content"]
                fake_calls.append("sql")
                return (
                    '{"sql":"SELECT SUM(sales_records.gross_revenue - '
                    'sales_records.discount) AS net_revenue FROM sales_records '
                    'JOIN sites ON sales_records.site_id = sites.id",'
                    '"clarification":null}'
                )
            assert "Summarize the supplied SQL result" in messages[0]["content"]
            result_data = json.loads(messages[1]["content"])
            assert result_data["rows"][0]["net_revenue"] == expected_revenue
            fake_calls.append("summary")
            return f"Net revenue for the selected period was {expected_revenue:,.2f}."

    fake_calls: list[str] = []
    monkeypatch.setattr("chat.routes.chat._client", FakeLLM)
    request_id = str(uuid4())
    today = date.today()
    start_date = today - timedelta(days=29)
    expected_revenue = client.get(
        "/api/analytics/overview",
        params={
            "site_id": site_id,
            "start_date": start_date.isoformat(),
            "end_date": today.isoformat(),
        },
    ).json()["revenue"]
    with client.websocket_connect(
        f"/api/chat/conversations/{conversation_id}/ws",
        headers={"origin": "http://testserver"},
    ) as websocket:
        websocket.send_json(
            {
                "type": "message",
                "request_id": request_id,
                "content": "How much did I sell?",
                "filters": {
                    "site_id": site_id,
                    "product_id": None,
                    "start_date": start_date.isoformat(),
                    "end_date": today.isoformat(),
                },
            }
        )
        events = []
        while True:
            event = websocket.receive_json()
            events.append(event)
            if event["type"] == "assistant.done":
                break
        websocket.send_json(
            {
                "type": "message",
                "request_id": request_id,
                "content": "How much did I sell?",
                "filters": {
                    "site_id": site_id,
                    "product_id": None,
                    "start_date": start_date.isoformat(),
                    "end_date": today.isoformat(),
                },
            }
        )
        replay = []
        while True:
            event = websocket.receive_json()
            replay.append(event)
            if event["type"] == "assistant.done":
                break
        websocket.send_json(
            {
                "type": "message",
                "request_id": request_id,
                "content": "Different question",
                "filters": {
                    "site_id": site_id,
                    "product_id": None,
                    "start_date": start_date.isoformat(),
                    "end_date": today.isoformat(),
                },
            }
        )
        conflict = websocket.receive_json()

    answer_events = [event for event in events if event["type"] == "assistant.delta"]
    answer = "".join(event["content"] for event in answer_events)
    assert answer_events
    assert "net revenue for the selected period was" in answer.lower()
    assert f"{expected_revenue:,.2f}" in answer
    assert events[-1] == {"type": "assistant.done", "request_id": request_id}
    assert "".join(
        event.get("content", "")
        for event in replay
        if event["type"] == "assistant.delta"
    ) == answer
    assert conflict["code"] == "request_id_conflict"
    assert fake_calls == ["sql", "summary"]
    history = client.get(
        f"/api/chat/conversations/{conversation_id}/messages"
    ).json()
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert history[1]["metadata_json"]["rows"][0]["net_revenue"] == expected_revenue
    assert history[0]["request_id"] == request_id
    latest_page = client.get(
        f"/api/chat/conversations/{conversation_id}/messages?limit=1"
    ).json()
    assert [item["role"] for item in latest_page] == ["assistant"]
    earlier_page = client.get(
        f"/api/chat/conversations/{conversation_id}/messages"
        f"?limit=1&before_id={latest_page[0]['id']}"
    ).json()
    assert [item["role"] for item in earlier_page] == ["user"]
    with session_factory() as db:
        conversation = db.get(ChatConversation, conversation_id)
        assert conversation is not None
        assert conversation.user_id == user_id
        assert db.query(ChatMessage).filter_by(conversation_id=conversation_id).count() == 2
    assert client.delete(f"/api/chat/conversations/{conversation_id}").status_code == 204
    with session_factory() as db:
        assert db.query(ChatMessage).filter_by(conversation_id=conversation_id).count() == 0


def test_analytics_agent_tools_cover_groupings_comparisons_and_empty_ranges(
    chat_client,
):
    client, session_factory = chat_client
    user_id = register(client, "chat-analytics@example.com")
    today = date.today()
    filters = ChatFilters(
        start_date=today - timedelta(days=29),
        end_date=today,
    )
    with session_factory() as db:
        user = db.get(User, user_id)
        assert user is not None
        products = run_analytics_tool(db, user, "products", "revenue", filters)
        sites = run_analytics_tool(db, user, "sites", "average_order_value", filters)
        comparison = run_analytics_tool(db, user, "comparison", "revenue", filters)
        empty = run_analytics_tool(
            db,
            user,
            "overview",
            "revenue",
            ChatFilters(start_date=today + timedelta(days=1), end_date=today + timedelta(days=1)),
        )
    assert products["rows"]
    assert "average_order_value" in products["rows"][0]
    assert len(sites["rows"]) == 2
    assert comparison["current"]["filters"]["start_date"] == filters.start_date.isoformat()
    assert empty["metrics"]["orders"] == 0


def test_websocket_rejects_another_users_site_before_persisting(chat_client):
    client, session_factory = chat_client
    first_user_id = register(client, "chat-site-owner@example.com")
    first_token = client.cookies.get("mic_session")
    first_conversation = client.post("/api/chat/conversations", json={}).json()["id"]
    first_site_ids = {site["id"] for site in client.get("/api/analytics/sites").json()}

    register(client, "chat-site-outsider@example.com")
    second_site_id = next(
        site["id"]
        for site in client.get("/api/analytics/sites").json()
        if site["id"] not in first_site_ids
    )
    client.cookies.set("mic_session", first_token)
    today = date.today()
    with client.websocket_connect(
        f"/api/chat/conversations/{first_conversation}/ws",
        headers={"origin": "http://testserver"},
    ) as websocket:
        websocket.send_json(
            {
                "type": "message",
                "request_id": str(uuid4()),
                "content": "Show me sales",
                "filters": {
                    "site_id": second_site_id,
                    "start_date": today.isoformat(),
                    "end_date": today.isoformat(),
                },
            }
        )
        event = websocket.receive_json()
    assert event["type"] == "error"
    assert event["code"] == "invalid_filter"
    with session_factory() as db:
        assert (
            db.query(ChatMessage)
            .join(ChatConversation)
            .filter(ChatConversation.user_id == first_user_id)
            .count()
            == 0
        )


@pytest.mark.parametrize(
    ("provider", "expected_model"),
    [
        ("openai", "gpt-4o-mini"),
        ("anthropic", "claude-3-5-haiku-latest"),
        ("gemini", "gemini-2.0-flash"),
        ("ollama", "llama3.2"),
    ],
)
def test_llm_factory_supports_each_provider(provider: str, expected_model: str):
    client = create_llm_client(
        LLMConfig(
            provider=provider,
            model=None,
            api_key="test-key" if provider != "ollama" else None,
            base_url=None,
            timeout_seconds=5,
            max_tokens=100,
        )
    )
    assert client.provider == provider
    assert client.model == expected_model
    assert client.capabilities.streaming
    messages = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "question"},
    ]
    body = client._body(messages, True)
    url = client._url(True)
    assert body
    if provider == "gemini":
        assert "streamGenerateContent" in url
        assert body["systemInstruction"]["parts"][0]["text"] == "rules"
    elif provider == "anthropic":
        assert url.endswith("/messages")
        assert body["system"] == "rules"
        assert body["stream"]
    elif provider == "openai":
        assert url.endswith("/chat/completions")
        assert body["stream"]
    else:
        assert url.endswith("/api/chat")
        assert body["stream"]


def test_llm_factory_reports_missing_credentials_and_unknown_provider():
    config = LLMConfig(
        provider="openai",
        model=None,
        api_key=None,
        base_url=None,
        timeout_seconds=5,
        max_tokens=100,
    )
    with pytest.raises(LLMProviderError, match="CHAT_OPENAI_API_KEY"):
        create_llm_client(config)._headers()
    with pytest.raises(LLMProviderError, match="CHAT_LLM_PROVIDER"):
        create_llm_client(
            LLMConfig(
                provider="unknown",
                model=None,
                api_key=None,
                base_url=None,
                timeout_seconds=5,
                max_tokens=100,
            )
        )


def test_sql_agent_rejects_unsafe_model_generated_sql(chat_client):
    client, session_factory = chat_client
    user_id = register(client, "chat-agent-security@example.com")

    class MaliciousLLM:
        async def complete(self, _messages: list[dict[str, str]]) -> str:
            return '{"sql":"DROP TABLE users","clarification":null}'

    with session_factory() as db:
        user = db.get(User, user_id)
        assert user is not None
        filters = ChatFilters(
            start_date=date.today() - timedelta(days=1),
            end_date=date.today(),
        )
        with pytest.raises(SQLAgentError, match="read-only analytics safety checks"):
            asyncio.run(
                SQLAgent(MaliciousLLM()).answer(db, user, "delete all data", filters)
            )


def test_sql_agent_executes_generated_aggregate_and_summarizes(chat_client):
    client, session_factory = chat_client
    user_id = register(client, "chat-agent-average-order-value@example.com")

    class AverageOrderValueLLM:
        calls = 0

        async def complete(self, messages: list[dict[str, str]]) -> str:
            self.calls += 1
            if self.calls == 1:
                return (
                    '{"sql":"SELECT AVG(sales_records.gross_revenue - '
                    'sales_records.discount) AS average_order_value FROM sales_records '
                    'JOIN sites ON sales_records.site_id = sites.id",'
                    '"clarification":null}'
                )
            summary_request = json.loads(messages[1]["content"])
            assert summary_request["row_count"] == 1
            return "The average order value for the selected period is summarized."

    llm = AverageOrderValueLLM()
    with session_factory() as db:
        user = db.get(User, user_id)
        assert user is not None
        filters = ChatFilters(
            start_date=date.today() - timedelta(days=1),
            end_date=date.today(),
        )
        answer, result = asyncio.run(
            SQLAgent(llm).answer(
                db, user, "What was my average order value?", filters
            )
        )

    assert result["columns"] == ["average_order_value"]
    assert result["row_count"] == 1
    assert "average order value" in answer


def test_sql_agent_retries_invalid_model_format(chat_client):
    client, session_factory = chat_client
    user_id = register(client, "chat-agent-format-retry@example.com")

    class RetryingLLM:
        calls = 0

        async def complete(self, _messages: list[dict[str, str]]) -> str:
            self.calls += 1
            if self.calls == 1:
                return "I will calculate that for you."
            if self.calls == 2:
                return (
                    '{"sql":"SELECT COUNT(*) AS order_count FROM sales_records '
                    'JOIN sites ON sales_records.site_id = sites.id",'
                    '"clarification":null}'
                )
            return "There are sales records in the selected period."

    llm = RetryingLLM()
    with session_factory() as db:
        user = db.get(User, user_id)
        assert user is not None
        filters = ChatFilters(
            start_date=date.today() - timedelta(days=1),
            end_date=date.today(),
        )
        answer, result = asyncio.run(
            SQLAgent(llm).answer(db, user, "How many orders?", filters)
        )

    assert llm.calls == 3
    assert result["columns"] == ["order_count"]
    assert "sales records" in answer


def test_sql_agent_mcp_tools_scope_query_to_user_and_dashboard_filters(chat_client):
    client, session_factory = chat_client
    first_user_id = register(client, "chat-sql-scope-first@example.com")
    first_site_id = client.get("/api/analytics/sites").json()[0]["id"]
    register(client, "chat-sql-scope-second@example.com")

    filters = ChatFilters(
        site_id=first_site_id,
        product_id=None,
        start_date=date.today() - timedelta(days=2),
        end_date=date.today(),
    )
    query = (
        "SELECT COUNT(*) AS order_count FROM sales_records "
        "JOIN sites ON sales_records.site_id = sites.id"
    )
    with session_factory() as db:
        first_user = db.get(User, first_user_id)
        assert first_user is not None
        server = create_sql_agent_mcp_server(db, first_user, filters)
        async def invoke_tools():
            async with create_connected_server_and_client_session(
                server, raise_exceptions=True
            ) as mcp_client:
                tools = await mcp_client.list_tools()
                assert {tool.name for tool in tools.tools} == {
                    "get_sales_schema",
                    "execute_readonly_sql",
                }
                schema = await mcp_client.call_tool("get_sales_schema", {})
                assert not schema.isError
                assert "sales_records" in schema.structuredContent["schema"]
                assert "sql_agent_bench" not in schema.structuredContent["schema"]
                return await mcp_client.call_tool(
                    "execute_readonly_sql", {"sql": query}
                )

        mcp_result = asyncio.run(invoke_tools())
        assert not mcp_result.isError
        result = mcp_result.structuredContent
        assert result is not None
        assert result["row_count"] == 1
        assert result["filters"]["site_id"] == first_site_id
        assert result["rows"][0]["order_count"] > 0


def test_generated_sql_cannot_or_around_injected_scope():
    filters = ChatFilters(
        start_date=date.today() - timedelta(days=1),
        end_date=date.today(),
    )
    query = (
        "SELECT COUNT(*) AS record_count FROM sales_records "
        "JOIN sites ON sales_records.site_id = sites.id "
        "WHERE sites.name = 'first' OR sites.name = 'second'"
    )
    safe_sql, _ = validate_and_scope_sql(query, filters)
    assert (
        "(sites.user_id = :authenticated_user_id AND "
        "sales_records.site_id = sites.id AND "
        "sales_records.sale_date >= :start_date AND "
        "sales_records.sale_date <= :end_date) AND "
        "(sites.name = 'first' OR sites.name = 'second')"
    ) in safe_sql


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM sales_records",
        "SELECT * FROM sales_records JOIN sites ON sales_records.site_id = sites.id",
        "SELECT users.email FROM users JOIN sites ON users.id = sites.user_id",
        "SELECT sales_records.gross_revenue FROM sales_records",
        (
            "WITH scoped_sales AS (SELECT sales_records.id FROM sales_records) "
            "SELECT COUNT(*) FROM scoped_sales JOIN sites ON true"
        ),
        (
            "SELECT COUNT(*) FROM sales_records AS sr "
            "JOIN sites ON sr.site_id = sites.id"
        ),
        (
            "SELECT pg_sleep(10) AS delayed FROM sales_records "
            "JOIN sites ON sales_records.site_id = sites.id"
        ),
        (
            "SELECT COUNT(*) FROM sales_records "
            "JOIN sites ON sales_records.site_id = sites.id "
            "WHERE pg_sleep(10) IS NULL"
        ),
        (
            "SELECT COUNT(*) FROM sales_records "
            "JOIN sites ON sales_records.site_id = sites.id -- trailing comment"
        ),
        (
            "SELECT COUNT(*) FROM sales_records "
            "JOIN sites ON sales_records.site_id = sites.id; DELETE FROM sites"
        ),
    ],
)
def test_generated_sql_rejects_unsafe_shapes(query: str):
    today = date.today()
    filters = ChatFilters(start_date=today, end_date=today)
    with pytest.raises(SQLAgentError, match="read-only analytics safety checks"):
        validate_and_scope_sql(query, filters)


def test_provider_configuration_failures_are_explicit(
    chat_client, monkeypatch: pytest.MonkeyPatch
):
    client, _ = chat_client
    register(client, "chat-provider-error@example.com")
    conversation_id = client.post("/api/chat/conversations", json={}).json()["id"]
    site_id = client.get("/api/analytics/sites").json()[0]["id"]
    monkeypatch.setattr(settings, "chat_llm_provider", "openai")
    monkeypatch.setattr(settings, "chat_openai_api_key", "")
    today = date.today()
    with client.websocket_connect(
        f"/api/chat/conversations/{conversation_id}/ws",
        headers={"origin": "http://testserver"},
    ) as websocket:
        websocket.send_json(
            {
                "type": "message",
                "request_id": str(uuid4()),
                "content": "Show my sales",
                "filters": {
                    "site_id": site_id,
                    "start_date": today.isoformat(),
                    "end_date": today.isoformat(),
                },
            }
        )
        event = websocket.receive_json()
    assert event["type"] == "error"
    assert event["code"] == "provider_error"
    assert "CHAT_OPENAI_API_KEY" in event["message"]


def test_websocket_rate_limit_counts_messages_across_requests(
    chat_client, monkeypatch: pytest.MonkeyPatch
):
    client, _ = chat_client
    register(client, "chat-rate-limit@example.com")
    conversation_id = client.post("/api/chat/conversations", json={}).json()["id"]
    monkeypatch.setattr("chat.routes.chat.MAX_MESSAGES_PER_MINUTE", 1)

    class ClarifyingLLM:
        async def complete(self, _messages: list[dict[str, str]]) -> str:
            return '{"sql":null,"clarification":"Please ask about sales analytics."}'

    monkeypatch.setattr("chat.routes.chat._client", ClarifyingLLM)
    today = date.today().isoformat()
    with client.websocket_connect(
        f"/api/chat/conversations/{conversation_id}/ws",
        headers={"origin": "http://testserver"},
    ) as websocket:
        websocket.send_json(
            {
                "type": "message",
                "request_id": str(uuid4()),
                "content": "Hello",
                "filters": {
                    "start_date": today,
                    "end_date": today,
                },
            }
        )
        assert websocket.receive_json()["type"] == "assistant.delta"
        assert websocket.receive_json()["type"] == "assistant.done"
        websocket.send_json(
            {
                "type": "message",
                "request_id": str(uuid4()),
                "content": "Show sales",
                "filters": {
                    "start_date": today,
                    "end_date": today,
                },
            }
        )
        rate_error = websocket.receive_json()
    assert rate_error["code"] == "rate_limited"
