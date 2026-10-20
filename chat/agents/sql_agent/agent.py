from sqlalchemy.orm import Session

from chat.agents.sql_agent.graph import SQLAgentState, build_sql_agent_graph
from chat.agents.sql_agent.mcp_server import create_sql_agent_mcp_server
from chat.agents.sql_agent.schemas import SQLAgentError
from chat.schemas import ChatFilters
from chat.utils.llm_factory import LLMClient
from middleware.models import User
from mcp.shared.memory import create_connected_server_and_client_session

SQL_AGENT_GRAPH = build_sql_agent_graph()


class SQLAgent:
    def __init__(self, client: LLMClient) -> None:
        self.graph = SQL_AGENT_GRAPH
        self.client = client

    async def answer(
        self,
        db: Session,
        user: User,
        question: str,
        filters: ChatFilters,
    ) -> tuple[str, dict]:
        server = create_sql_agent_mcp_server(db, user, filters)
        graph_result: dict | None = None
        graph_error: Exception | None = None
        async with create_connected_server_and_client_session(
            server, raise_exceptions=True
        ) as mcp_session:
            initial_state: SQLAgentState = {
                "client": self.client,
                "mcp_session": mcp_session,
                "question": question,
                "filters": filters,
            }
            try:
                graph_result = await self.graph.ainvoke(initial_state)
            except Exception as error:
                graph_error = error
        if graph_error is not None:
            raise graph_error
        if graph_result is None:
            raise SQLAgentError("The analytics agent did not complete the request.")
        result = graph_result
        answer = result.get("answer")
        metadata = result.get("result")
        if not isinstance(answer, str) or not isinstance(metadata, dict):
            raise SQLAgentError("The analytics agent did not complete the request.")
        return answer, metadata
