# Chat feature

Chat-specific backend code belongs in this repository-root directory, outside `middleware/`.
The middleware application remains responsible for registering the chat router and providing
shared authentication and database dependencies. The dashboard UI stays in the existing
`frontend/` application, and Alembic migrations stay in `middleware/migrations/` to use the
configured migration workflow.

SQL-agent schema discovery and query execution are exposed as request-scoped MCP tools in
`agents/sql_agent/mcp_server.py`. The LangGraph agent accesses these tools through an MCP
client; graph nodes must not execute database queries directly. The in-process MCP server
binds each call to the authenticated user and the request's validated dashboard filters.
