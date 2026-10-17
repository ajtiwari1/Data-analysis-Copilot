# Dashboard Chat Implementation Plan

## Goal and scope

Add an authenticated chat assistant to the sales analytics dashboard. Users should be able to ask questions about their sites, products, and sales, receive answers grounded in their PostgreSQL data, and use suggested prompts to explore the dashboard.

The first version is an analytics assistant, not a general-purpose chatbot. It must not invent metrics, access another user's records, or execute model-generated SQL. A constrained SQL agent may interpret analytics questions and select approved query operations, but it must only invoke allow-listed, parameterized analytics functions; it must never run raw SQL authored by the model. If the assistant cannot answer from available analytics, it should say so clearly.

## Chat code location

- Keep chat-specific backend implementation in a new repository-root `chat/` package, outside `middleware/`.
- Organize chat models, routes, analytics/agent services, and shared LLM utilities under `chat/`; keep the existing middleware as the application host that wires in the chat router and supplies shared authentication and database dependencies.
- Put provider-independent LLM interfaces and provider adapters in `chat/utils/llm_factory/`. Chat and agent code should call the same interface regardless of the configured provider; select the adapter and model through server-side environment configuration.
- Put the chat UI in the existing frontend application. Keep Alembic migration scripts in the repository's configured `middleware/migrations/` location so the existing migration workflow continues to discover and apply them.

## 1. Define the chat experience and provider

- Add a chat panel to the post-login dashboard, with a responsive layout that works alongside the sales charts and filters.
- Include an initial greeting, suggested questions, message history, loading/streaming state, retry behavior, and clear error states.
- Suggested prompts should use existing dashboard context, for example:
  - "Which products earned the most this month?"
  - "How did sales change compared with the previous period?"
  - "Which site had the highest average order value?"
- Keep the active site, product, and date filters available as context for questions; make it clear when a response uses those filters.
- Use the provider-neutral interface and factory in `chat/utils/llm_factory/`, with adapters for OpenAI, Anthropic, Gemini, and Ollama. OpenAI (`gpt-4o-mini`) is the default; provider and model are configurable, and changing providers must not affect routes, chat logic, or UI.
- Keep model name, API endpoint, and API key in environment configuration; never expose secrets to the browser or commit them.
- Define provider timeout, retry, token limit, and cost/rate-limit expectations before enabling production use.
- Make provider capabilities explicit in the interface (including streaming and tool/function calling); fail clearly when the selected provider does not support a required capability.

## 2. Persist conversations in PostgreSQL

- Add SQLAlchemy models under `chat/models/` for chat conversations and messages.
- Associate every conversation with its owner (`user_id`); associate messages with a conversation and store role, content, creation time, and any safe metadata needed for citations or request status.
- Use migrations under `middleware/migrations/` with foreign keys, indexes, ownership constraints, and cascade behavior.
- Store user and assistant messages only after validating request size and authorization. Do not store provider credentials, hidden prompts, or unnecessary sensitive data.
- Define retention and deletion behavior for conversations. Provide a way for a user to delete a conversation and its messages.
- Keep conversation history bounded when constructing model context; avoid sending an unbounded transcript to the provider.

## 3. Build a grounded analytics tool layer and SQL agent

- Implement reusable analytics query functions under `chat/services/` that use the existing sales models and validated filters.
- Implement a SQL agent under `chat/agents/` that maps a user's question to a typed, validated analytics query plan and calls only the approved functions below. The LLM may select a tool and provide arguments, but may not create or execute SQL statements.
- Build database queries in application code with SQLAlchemy expressions and bound parameters. Enforce read-only access, authenticated-user scoping, table/column and row limits, and query timeouts; never expose database credentials or unrestricted schema access to the model.
- Expose a small allow-listed set of read-only tools, such as:
  - sales totals and time series for a date range;
  - sales grouped by site;
  - sales grouped by product;
  - period-over-period comparisons.
- Always derive the account scope from the authenticated user. Validate that requested site/product IDs belong to that user.
- Have tools return structured values with metric definitions, date range, currency, and source identifiers for the answer; do not allow arbitrary SQL, writes, or unrestricted database access from the model.
- Have the SQL agent ground final answers only in returned tool results; when the question cannot map safely to an approved operation, ask for clarification or explain the limitation.
- For each response, retain enough source detail to explain which date range/site/product filters informed the answer.
- When a question is ambiguous (for example, "best" without specifying revenue or units), ask a short clarifying question or state the metric assumption.
- If no matching data exists, say that no data was found rather than estimating or fabricating values.

## 4. Add authenticated chat API routes

- Add the chat router under `chat/routes/` and register it with the application from the middleware integration layer.
- Require the existing `CurrentUser` dependency for every route.
- Provide endpoints to:
  - list the signed-in user's conversations;
  - create a conversation;
  - fetch a conversation and its paginated messages;
  - delete a conversation.
- Use an authenticated WebSocket for chat message exchange, connected to a single conversation. Authenticate the handshake with the existing session mechanism, and reject connections to conversations not owned by the signed-in user.
- Define a small, typed WebSocket event protocol for client messages, assistant response chunks, completion, and errors. Validate every incoming event and enforce message size, rate, timeout, and response-length limits.
- Persist the user's message and the completed assistant response; report provider or connection failures explicitly and avoid treating an incomplete response as successful. Include a client-generated request ID so reconnect/retry handling can avoid accidental duplicate sends.
- Scope every database lookup and mutation by both conversation ID and authenticated user ID to prevent IDOR/cross-user access.
- Validate message length, request shape, selected filters, and conversation ownership. Return consistent authentication, validation, and provider error responses.
- Rate-limit message requests and bound provider calls and response length.

## 5. Build the frontend chat UI

- Add typed chat API helpers alongside the existing frontend API client.
- Add a chat panel with conversation selection/history, message list, multiline composer, send action, suggested prompts, and accessible status announcements.
- Connect the composer to the conversation's authenticated WebSocket; render assistant response chunks as they arrive and handle connection, completion, and error states accessibly.
- Send the current dashboard filters with each analytics question; allow the user to see or change the filters used for the answer.
- Render assistant messages as safe text/Markdown; sanitize or disallow raw HTML and unsafe links.
- Keep history and loading/error states synchronized with the persisted API conversation.
- Handle expired sessions by using the existing auth flow; do not store conversation data or session secrets in local storage.
- Support narrow screens by making chat a tab, drawer, or stacked panel without hiding essential dashboard controls.

## 6. Security, privacy, and reliability

- Keep provider keys only on the backend and redact credentials and sensitive data from application logs.
- Do not send password hashes, session tokens, or unrelated account information to the model provider.
- Send only the minimum relevant analytics data needed for each answer.
- Apply message length limits, request timeouts, rate limits, and bounded conversation context.
- Return a clear user-facing error if the provider is unavailable; do not present an error-shaped response as a successful answer.
- Document whether chat messages and analytics context are sent to a third-party model provider and what retention applies.

## 7. Test and document

- Test conversation creation, message persistence, pagination, deletion, and ownership enforcement.
- Test unauthenticated access rejection and cross-user conversation/site/product isolation.
- Test each analytics tool against known PostgreSQL fixtures, including date boundaries, zero-result cases, and multiple sites.
- Test that the SQL agent only selects allow-listed tools, validates arguments and user scope, and cannot execute model-authored SQL; test the LLM factory's provider selection, shared interface, streaming, and unsupported-capability errors.
- Test that model prompts/results use only tool-provided numbers and that provider failures, timeouts, invalid tool arguments, and oversized messages are handled explicitly.
- Test dashboard filter context, send/retry behavior, empty history, loading/error states, keyboard use, and small-screen layout.
- Add API documentation, provider environment variables, migration instructions, retention policy, and local setup instructions to `README.md`.

## Suggested implementation order

1. Define the provider-neutral LLM interface, provider/model defaults, and privacy, retention, and rate limits.
2. Add conversation/message models and an Alembic migration.
3. Implement and test the allow-listed analytics tools and constrained SQL agent using existing PostgreSQL data.
4. Add authenticated conversation routes and WebSocket messaging with ownership checks and persistence.
5. Add the dashboard chat interface and connect it to the WebSocket and conversation API.
6. Run the migration, verify end-to-end behavior with multiple users, and document configuration.
