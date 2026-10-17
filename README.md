# Marketing Intelligence Copilot

Authentication uses a FastAPI backend, a React/Vite frontend, PostgreSQL user and session records, and an HTTP-only session cookie. Passwords are hashed with Argon2id. The browser never stores the session token in local storage.

## Backend layout

Backend code lives in `middleware/`:

- `routes/` contains API route modules; add a route module there and include its router from `routes/__init__.py`.
- `models/` contains SQLAlchemy models; export new models from `models/__init__.py` so migrations discover them.
- `database/` contains the SQLAlchemy base, engine, session factory, and database dependency.
- `migrations/` contains Alembic configuration and schema revisions.
- `main.py` creates the FastAPI application and registers the combined API router.
- `schemas.py`, `dependencies.py`, `security.py`, and `config.py` hold shared API schemas, request dependencies, auth helpers, and settings.
- The repository-root `chat/` package contains chat models, routes, analytics tools, the constrained SQL agent, and provider-neutral LLM utilities. Middleware registers the chat router and supplies shared authentication and database dependencies.

## Run the full stack with Docker Compose

1. Copy `.env.example` to `.env` and set `POSTGRES_PASSWORD` to a development password.
2. Start PostgreSQL, the API, and the frontend:

   ```sh
   docker compose up --build -d
   ```

3. Open `http://localhost:8080`. Compose runs the database migration before starting the API. The frontend's Nginx server proxies `/api` requests to FastAPI.

Stop the services with `docker compose down`. PostgreSQL data remains in the `postgres_data` volume. To remove that data as well, use `docker compose down -v`.

## Run services individually

1. Copy `.env.example` to `.env` and set `POSTGRES_PASSWORD` to a development password. `.env` is ignored by Git.
2. Start PostgreSQL: `docker compose up -d`.
3. Use Python 3.11 or newer. From the repository root, create and activate a virtual environment, then install backend dependencies:

   ```sh
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements-dev.txt
   ```

4. Apply the database migration:

   ```sh
   alembic -c middleware/alembic.ini upgrade head
   ```

5. Start the API from the repository root:

   ```sh
   uvicorn middleware.main:app --reload
   ```

6. In a second terminal, install and start the frontend:

   ```sh
   cd frontend
   npm install
   npm run dev
   ```

Open the Vite URL (normally `http://localhost:5173`). The development server proxies `/api` requests to FastAPI at `http://localhost:8000`.

## Configuration

The root `.env` configures PostgreSQL, the API, and published ports:

| Variable | Purpose | Default |
| --- | --- | --- |
| `POSTGRES_DB` | Database created by Compose | `marketing_intelligence` |
| `POSTGRES_USER` | PostgreSQL role created by Compose | `postgres` |
| `POSTGRES_PASSWORD` | PostgreSQL role password | `postgres` in `.env.example`; change it |
| `POSTGRES_PORT` | Host port for PostgreSQL | `5432` |
| `API_PORT` | Host port for the API | `8000` |
| `FRONTEND_PORT` | Host port for the frontend | `8080` |
| `DATABASE_URL` | Optional SQLAlchemy URL override; otherwise the API derives the URL from `POSTGRES_*` | Derived from the PostgreSQL settings |
| `SESSION_COOKIE_SECURE` | Require HTTPS for the session cookie | `false` in `.env.example`; set `true` in production |
| `FRONTEND_ORIGIN` | Allowed frontend origin for credentialed API requests | `http://localhost:5173` |
| `CHAT_LLM_PROVIDER` | LLM backend: `openai`, `anthropic`, `gemini`, or `ollama` | `openai` |
| `CHAT_LLM_MODEL` | Optional provider-specific model override | Provider default |
| `CHAT_LLM_BASE_URL` | Optional provider API base URL override | Provider default |
| `CHAT_LLM_TIMEOUT_SECONDS` | Provider request timeout | `30` |
| `CHAT_LLM_MAX_TOKENS` | Maximum provider output tokens | `800` |
| `CHAT_OPENAI_API_KEY` | OpenAI API key (only needed for OpenAI) | Empty |
| `CHAT_ANTHROPIC_API_KEY` | Anthropic API key (only needed for Anthropic) | Empty |
| `CHAT_GEMINI_API_KEY` | Google Gemini API key (only needed for Gemini) | Empty |

For local development with Vite, set `FRONTEND_ORIGIN=http://localhost:5173`; Compose serves the frontend at `http://localhost:8080` by default. For a frontend deployed on a separate origin within the same site, set `VITE_API_BASE_URL` in the frontend's Vite environment to the API origin and configure `FRONTEND_ORIGIN` to the exact frontend origin. This setup uses `SameSite=Lax` cookies; cross-site frontend/API deployments need additional CSRF protection and `SameSite=None` support, which are not implemented yet. Production must use HTTPS and `SESSION_COOKIE_SECURE=true`.

## Authentication routes

- `POST /api/auth/register` creates an account and signs it in.
- `POST /api/auth/login` signs in with an email and password.
- `GET /api/auth/me` restores the current session.
- `POST /api/auth/logout` invalidates the current session and clears its cookie.
- `GET /api/dashboard` is an example protected API route.

Passwords must be 12–128 characters. The API stores a SHA-256 digest of each random session token in PostgreSQL; only the raw token is sent in an HTTP-only, SameSite=Lax cookie.

## Sales analytics and demo data

Registration writes two example sites, eight products, and 90 days of deterministic order-level sales records to PostgreSQL in the same transaction as the new account and session. The dashboard reads these records through protected APIs; demo charts are not hard-coded in the browser.

- `GET /api/analytics/sites` lists the signed-in user's sites.
- `GET /api/analytics/products?site_id=<id>` lists that user's products, optionally scoped to one owned site.
- `GET /api/analytics/overview` returns revenue, distinct orders, units sold, daily sales, and product sales. It accepts optional `site_id`, `product_id`, `start_date`, and `end_date` filters (ISO dates). Dates default to the most recent 30 days.

Revenue means gross sales minus discounts; refunds are not modeled. Each daily record is one order/product line; order counts are distinct within a site. Combined revenue across sites is only returned when their currencies match. All included demo sites use USD.

## Chat assistant

Chat messages are exchanged through the authenticated WebSocket at
`/api/chat/conversations/{id}/ws`. Conversation list/create, paginated message history,
and deletion use `/api/chat/conversations`. Apply the chat schema with
`alembic -c middleware/alembic.ini upgrade head`. Send
`{type: "message", request_id: "<uuid>", content: "...", filters: {...}}`; responses are
`assistant.delta` chunks followed by `assistant.done`, or a structured `error` event. The
client request ID makes completed retries idempotent.

Set `CHAT_LLM_PROVIDER` to `openai`, `anthropic`, `gemini`, or `ollama`. Provider API keys
remain server-side in `.env`; Ollama defaults to `http://localhost:11434` and does not need
an API key. Default models are `gpt-4o-mini`, `claude-3-5-haiku-latest`,
`gemini-2.0-flash`, and `llama3.2`, respectively. The SQL agent only classifies a question
into a fixed analytics operation. Queries are built by application code using authenticated
user scope and SQLAlchemy expressions; the model cannot issue SQL.
Message sends are limited to 10 per user per minute, enforced through the database across
API workers. Provider calls time out after 30 seconds by default, and output is bounded by
`CHAT_LLM_MAX_TOKENS` (800 by default). Provider calls are not automatically retried; use the
client retry action, which is idempotent for completed requests. Provider cost varies by
selected model; request and token limits bound usage but do not replace provider-side spending
limits or budget alerts in production.

Chat messages and the selected analytics filters are stored in PostgreSQL until the user
deletes the conversation. There is no automatic retention expiry yet. For hosted providers,
only the user's question is sent for operation classification; site/product/date filters and
query results remain on the backend, and answers are formatted from those local query results.
Provider-side handling and retention for the question are governed by that provider's terms.
Ollama runs against the configured local server.

Apply database migrations after pulling schema changes with `alembic -c middleware/alembic.ini upgrade head`. To insert missing demo records for existing accounts, run `python -m middleware.seed_demo --all-users`, or target one account with `python -m middleware.seed_demo --email user@example.com`. The command is idempotent and runs locally/admin-side; there is no public seed endpoint. Expired sessions can be removed periodically with `python -m middleware.maintenance`; schedule this command as a daily job in deployments.

## Tests

Run backend authentication tests with `pytest`.
