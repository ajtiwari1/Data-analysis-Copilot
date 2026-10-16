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

For local development with Vite, set `FRONTEND_ORIGIN=http://localhost:5173`; Compose serves the frontend at `http://localhost:8080` by default. For a frontend deployed on a separate origin within the same site, set `VITE_API_BASE_URL` in the frontend's Vite environment to the API origin and configure `FRONTEND_ORIGIN` to the exact frontend origin. This setup uses `SameSite=Lax` cookies; cross-site frontend/API deployments need additional CSRF protection and `SameSite=None` support, which are not implemented yet. Production must use HTTPS and `SESSION_COOKIE_SECURE=true`.

## Authentication routes

- `POST /api/auth/register` creates an account and signs it in.
- `POST /api/auth/login` signs in with an email and password.
- `GET /api/auth/me` restores the current session.
- `POST /api/auth/logout` invalidates the current session and clears its cookie.
- `GET /api/dashboard` is an example protected API route.

Passwords must be 12–128 characters. The API stores a SHA-256 digest of each random session token in PostgreSQL; only the raw token is sent in an HTTP-only, SameSite=Lax cookie.

Run `alembic -c middleware/alembic.ini upgrade head` after pulling schema changes. Expired sessions can be removed periodically with `python -m middleware.maintenance`; schedule this command as a daily job in deployments.

## Tests

Run backend authentication tests with `pytest`.
