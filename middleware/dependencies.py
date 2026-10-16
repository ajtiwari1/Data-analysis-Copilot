from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from middleware.config import settings
from middleware.database import get_db
from middleware.models import AuthSession, User
from middleware.security import create_session_token, hash_session_token

SESSION_COOKIE_NAME = "mic_session"
DbSession = Annotated[Session, Depends(get_db)]


def issue_session(response: Response, user: User, db: Session) -> None:
    token = create_session_token()
    now = datetime.now(UTC)
    db.add(
        AuthSession(
            token_hash=hash_session_token(token),
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(seconds=settings.session_ttl_seconds),
        )
    )
    db.commit()
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def get_current_user(request: Request, db: DbSession) -> User:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )

    user = db.scalar(
        select(User)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(
            AuthSession.token_hash == hash_session_token(token),
            AuthSession.expires_at > datetime.now(UTC),
        )
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
