# Authentication Implementation Plan

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
