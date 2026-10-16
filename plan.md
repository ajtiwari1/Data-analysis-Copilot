# Authentication and Analytics Implementation Plan

This plan covers backend middleware and frontend changes for adding user authentication. The selected stack is FastAPI with a React/Vite frontend. PostgreSQL stores user account records and server-managed sessions; the browser receives only a secure session cookie, not credentials or session secrets in local storage.

## 1. Define the authentication flow

- Identify public and protected pages, API routes, and user actions.
- Define sign-up, sign-in, sign-out, session restoration, and session-expiry behavior.
- Decide where users should land after signing in and where unauthenticated users should go when they request a protected page.
- Define whether the application needs roles or permissions beyond the basic signed-in state.

## 2. Implement backend authentication

- Add endpoints for sign-up, sign-in, current-session lookup, and sign-out.
- Validate and normalize submitted data on the server.
- Store account and authentication records in PostgreSQL.
- Hash passwords with a modern password-hashing algorithm (such as Argon2id); store only the resulting password hash, never plaintext passwords.
- Create and invalidate server-managed sessions, persisting session records in PostgreSQL.
- Set session cookies with `HttpOnly`, `Secure` in production, and an appropriate `SameSite` policy.
- Return consistent errors and avoid disclosing whether a particular account exists.

## 3. Add PostgreSQL persistence

- Create database migrations for the auth schema, including:
  - A users table with a primary key, normalized unique email (or chosen login identifier), password hash, and created/updated timestamps.
  - A sessions table with a primary key or securely generated session identifier, a user foreign key, expiry timestamp, and created timestamp.
- Add indexes for account lookup and session validation/expiry cleanup; enforce uniqueness and referential integrity in the database.
- Configure the database connection through environment-based configuration and keep secrets out of source control.
- Use parameterized queries or the project's established ORM/query layer, and run schema changes through migrations.
- Define retention and cleanup for expired sessions, and ensure sign-out invalidates the persisted session.

## 4. Add authentication middleware

- Read the session cookie and validate the matching, unexpired session in PostgreSQL on requests to protected endpoints.
- Attach the authenticated user's identity and relevant authorization data to the request context.
- Return `401 Unauthorized` when no valid session is present and `403 Forbidden` when the user lacks permission.
- Explicitly identify public routes and apply middleware to protected routes by default.
- Keep authorization enforcement on the server; frontend route guards are for user experience, not access control.
- Ensure session expiry, invalidation, and cookie-clearing behavior are handled consistently.

## 5. Build the frontend authentication experience

- Add sign-in and, if required, sign-up forms with accessible labels, validation, and pending/error states.
- Add a shared authentication state mechanism that fetches the current session when the application loads.
- Show a loading state while session restoration is in progress.
- Protect frontend routes by rendering the requested page for signed-in users and redirecting unauthenticated users to sign-in.
- Preserve the intended destination during sign-in and return the user there after successful authentication.
- Add a sign-out action that clears the server session and updates the frontend state.
- Display appropriate signed-in account information without treating client-side state as proof of authorization.

## 6. Test and document the end-to-end flow

- Test successful and failed sign-in/sign-up, session restoration, expiry, and sign-out.
- Test PostgreSQL migrations, uniqueness constraints, password-hash persistence, session lookup, and expired-session handling.
- Test that protected API routes reject unauthenticated requests and enforce permissions where applicable.
- Test frontend loading, redirects, return-to-destination behavior, and error display.
- Verify cookie attributes and ensure passwords, password hashes, session secrets, and database credentials are not exposed to the client or logs.
- Document PostgreSQL setup, required configuration, migrations, local development setup, and how to protect additional routes.

## Suggested implementation order

1. Confirm the application framework, session storage, and required auth flows.
2. Establish PostgreSQL configuration and create auth schema migrations.
3. Implement backend endpoints and PostgreSQL-backed account/session handling.
4. Apply and test authentication middleware on protected APIs.
5. Integrate frontend auth state, forms, route protection, and sign-out.
6. Run focused tests and document setup and extension points.

---

# Post-Login Sales Analytics Dashboard Plan

## Goal and scope

Replace the current post-login welcome panel with an analytics dashboard showing realistic, synthetic demo data for the signed-in user's marketing/e-commerce sites, products, and sales. This phase does not connect to external analytics platforms or payment systems.

## 1. Define the demo data

- Create two synthetic web properties for each user: a sample storefront (for example, `Northstar Outfitters`) and a campaign microsite (for example, `Trail Ready`), each with a display name, example URL, and currency.
- Include a small, coherent catalog such as a daypack, insulated bottle, trail jacket, and hiking socks, with SKU, category, and unit price.
- Add daily sales records associated with a site and product, including date, orders, units sold, gross revenue, and refunds or discounts if needed for net revenue.
- Generate deterministic records for the last 90 days, with distinct site trends, weekday variation, and a few best-selling products so the charts are informative and repeatable.
- Label the records as demo data in the UI; do not imply the records came from a live integration.

## 2. Persist demo data in PostgreSQL

- Add `Site`, `Product`, and `SalesRecord` models under `middleware/models/`.
- Use foreign keys and indexes to support user/site/product ownership and date-range queries.
- Ensure each signed-in user can access only their own sites and related products and sales.
- Add an Alembic migration for the new tables and constraints.
- Implement a backend seeding service that writes the example sites, products, and 90 days of sales records to PostgreSQL; the frontend must read these persisted records through the API, not use hard-coded chart data.
- Seed the user's records as part of successful account creation, in the same database transaction as the new user, so partial demo accounts are not left behind if seeding fails.
- Make seeding idempotent using database constraints and safe insert/upsert logic, so retries do not duplicate sites, products, or sales.
- Provide a development command to seed or verify demo data for an existing user, without exposing a public unauthenticated seed endpoint.
- Keep seeded sample data deterministic enough for tests and repeatable local demos.

## 3. Create protected analytics API routes

- Add routes under `middleware/routes/` for listing the current user's sites and products and retrieving dashboard analytics.
- Require the existing authenticated-user dependency on all analytics endpoints; derive the user scope from the session, never from a client-supplied user ID.
- Support optional site, product, and date-range filters, validating date order and ensuring selected records belong to the current user.
- Return aggregated time-series data and summary metrics rather than requiring the browser to download all raw records.
- Define and document metric semantics, including revenue basis (gross or net), order count, units sold, and average order value.

## 4. Build the post-login dashboard

- Replace the current welcome panel on `/` with a responsive dashboard while preserving the existing protected-route and sign-out behavior.
- Add a page heading, signed-in account information, demo-data indicator, and site/product/date-range filters.
- Show KPI cards for revenue, orders, units sold, and average order value.
- Default to the last 30 days within the 90-day demo dataset. Add a sales-over-time chart and a product comparison chart, using a React-compatible chart library such as Recharts, with readable labels, tooltips, empty states, and accessible text summaries.
- Show loading, API error, and no-data states; changing a filter should refresh the metrics and charts.
- Keep chart values and KPI totals consistent with the selected filters and API response.

## 5. Test, validate, and document

- Test migrations, demo-data seeding and idempotency, relationship constraints, and user-level data isolation.
- Verify that registration writes sites, products, and sales rows to PostgreSQL and that dashboard API results are aggregated from those rows.
- Test analytics calculations, date boundaries, filters, invalid filter values, and empty results.
- Test that unauthenticated requests are rejected and that one user cannot read another user's sites, products, or sales.
- Test dashboard loading, filter changes, chart data mapping, and API error/empty states.
- Verify that charts and KPI summaries work at desktop and mobile widths and provide accessible labels.
- Document the demo dataset, metric definitions, API filters, and how to reseed or reset local demo data.

## Suggested implementation order

1. Agree on the demo site/product examples and metric definitions.
2. Add models, migration, and repeatable per-user demo-data seeding.
3. Add and test protected analytics APIs and aggregation queries.
4. Add a chart library and implement the dashboard and filters.
5. Verify end-to-end behavior with multiple users and document local demo setup.
