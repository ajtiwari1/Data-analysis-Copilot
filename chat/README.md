# Chat feature

Chat-specific backend code belongs in this repository-root directory, outside `middleware/`.
The middleware application remains responsible for registering the chat router and providing
shared authentication and database dependencies. The dashboard UI stays in the existing
`frontend/` application, and Alembic migrations stay in `middleware/migrations/` to use the
configured migration workflow.
