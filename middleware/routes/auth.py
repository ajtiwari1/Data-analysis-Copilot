from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from middleware.config import settings
from middleware.dependencies import (
    CurrentUser,
    DbSession,
    SESSION_COOKIE_NAME,
    issue_session,
)
from middleware.models import AuthSession, User
from middleware.schemas import Credentials, UserResponse
from middleware.security import hash_password, hash_session_token, verify_password
from middleware.services.demo_data import seed_demo_data

router = APIRouter(prefix="/auth")


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    credentials: Credentials,
    response: Response,
    db: DbSession,
) -> User:
    user = User(
        email=str(credentials.email),
        password_hash=hash_password(credentials.password),
    )
    db.add(user)
    try:
        db.flush()
        seed_demo_data(db, user)
        issue_session(response, user, db)
    except IntegrityError as error:
        db.rollback()
        if db.scalar(select(User.id).where(User.email == str(credentials.email))):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists",
            ) from error
        raise
    return user


@router.post("/login", response_model=UserResponse)
def login(
    credentials: Credentials,
    response: Response,
    db: DbSession,
) -> User:
    user = db.scalar(select(User).where(User.email == str(credentials.email)))
    if user is None or not verify_password(user.password_hash, credentials.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    issue_session(response, user, db)
    return user


@router.get("/me", response_model=UserResponse)
def get_session_user(user: CurrentUser) -> User:
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    db: DbSession,
) -> Response:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        session = db.get(AuthSession, hash_session_token(token))
        if session is not None:
            db.delete(session)
            db.commit()

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return response
