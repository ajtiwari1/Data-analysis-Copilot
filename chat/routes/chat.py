"""Authenticated chat and conversation endpoints."""

from datetime import UTC, datetime, timedelta
import json
from time import time
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from chat.agents.sql_agent import SQLAgent, SQLAgentError
from chat.models import ChatConversation, ChatMessage, ChatRequestAttempt
from chat.schemas import (
    ChatFilters,
    ChatMessageResponse,
    ConversationCreate,
    ConversationResponse,
    WebSocketEvent,
    WebSocketMessage,
)
from chat.utils.llm_factory import (
    LLMConfig,
    LLMProviderError,
    create_llm_client,
)
from middleware.config import settings
from middleware.database import SessionLocal
from middleware.dependencies import CurrentUser, DbSession, SESSION_COOKIE_NAME
from middleware.models import AuthSession, Product, Site, User
from middleware.security import hash_session_token

router = APIRouter(prefix="/chat")
MAX_MESSAGES_PER_MINUTE = 10
PENDING_GRACE_SECONDS = 15


def _owned_conversation(db: Session, user: User, conversation_id: int) -> ChatConversation:
    conversation = db.scalar(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == user.id,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _validate_filters(db: Session, user: User, filters: ChatFilters) -> None:
    if filters.site_id is not None and db.scalar(
        select(Site.id).where(Site.id == filters.site_id, Site.user_id == user.id)
    ) is None:
        raise HTTPException(status_code=404, detail="Site not found")
    if filters.product_id is not None:
        query = (
            select(Product.id)
            .join(Site, Site.id == Product.site_id)
            .where(Product.id == filters.product_id, Site.user_id == user.id)
        )
        if filters.site_id is not None:
            query = query.where(Product.site_id == filters.site_id)
        if db.scalar(query) is None:
            raise HTTPException(status_code=404, detail="Product not found")


def _client():
    provider = settings.chat_llm_provider.strip().lower()
    api_keys = {
        "openai": settings.chat_openai_api_key,
        "anthropic": settings.chat_anthropic_api_key,
        "gemini": settings.chat_gemini_api_key,
        "ollama": None,
    }
    return create_llm_client(
        LLMConfig(
            provider=provider,
            model=settings.chat_llm_model or None,
            api_key=api_keys.get(provider),
            base_url=settings.chat_llm_base_url or None,
            timeout_seconds=settings.chat_llm_timeout_seconds,
            max_tokens=settings.chat_llm_max_tokens,
        )
    )


async def _send_answer(websocket: WebSocket, request_id: str, answer: str) -> None:
    chunk_size = 80
    for offset in range(0, len(answer), chunk_size):
        await _send_event(
            websocket,
            WebSocketEvent(
                type="assistant.delta",
                request_id=request_id,
                content=answer[offset : offset + chunk_size],
            ),
        )
    await _send_event(
        websocket, WebSocketEvent(type="assistant.done", request_id=request_id)
    )


async def _send_event(websocket: WebSocket, event: WebSocketEvent) -> None:
    await websocket.send_json(event.model_dump(exclude_none=True))


async def _send_error(
    websocket: WebSocket, request_id: str, code: str, message: str
) -> None:
    await _send_event(
        websocket,
        WebSocketEvent(
            type="error",
            request_id=request_id,
            code=code,
            message=message,
        ),
    )


@router.get("/conversations", response_model=list[ConversationResponse])
def list_conversations(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ChatConversation]:
    return list(
        db.scalars(
            select(ChatConversation)
            .where(ChatConversation.user_id == user.id)
            .order_by(ChatConversation.updated_at.desc())
            .limit(limit)
        ).all()
    )


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    body: ConversationCreate,
    user: CurrentUser,
    db: DbSession,
) -> ChatConversation:
    conversation = ChatConversation(user_id=user.id, title=body.title.strip())
    if not conversation.title:
        raise HTTPException(status_code=422, detail="Conversation title cannot be blank")
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[ChatMessageResponse],
)
def list_messages(
    conversation_id: int,
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before_id: Annotated[int | None, Query(gt=0)] = None,
) -> list[ChatMessage]:
    _owned_conversation(db, user, conversation_id)
    query = select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
    if before_id is not None:
        query = query.where(ChatMessage.id < before_id)
    return list(
        db.scalars(query.order_by(ChatMessage.id.desc()).limit(limit)).all()[::-1]
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_conversation(
    conversation_id: int,
    user: CurrentUser,
    db: DbSession,
) -> None:
    conversation = _owned_conversation(db, user, conversation_id)
    db.delete(conversation)
    db.commit()


@router.websocket("/conversations/{conversation_id}/ws")
async def chat_websocket(websocket: WebSocket, conversation_id: int) -> None:
    origin = websocket.headers.get("origin")
    if origin != settings.frontend_origin:
        await websocket.close(code=4403)
        return
    token = websocket.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        await websocket.close(code=4401)
        return

    with SessionLocal() as db:
        user = db.scalar(
            select(User)
            .join(AuthSession, AuthSession.user_id == User.id)
            .where(
                AuthSession.token_hash == hash_session_token(token),
                AuthSession.expires_at > datetime.now(UTC),
            )
        )
        if user is None:
            await websocket.close(code=4401)
            return
        conversation = db.scalar(
            select(ChatConversation).where(
                ChatConversation.id == conversation_id,
                ChatConversation.user_id == user.id,
            )
        )
        if conversation is None:
            await websocket.close(code=4403)
            return

        db.commit()
        await websocket.accept()
        while True:
            try:
                raw_message = await websocket.receive_text()
            except WebSocketDisconnect:
                return
            if len(raw_message) > 16_384:
                await _send_error(
                    websocket, "", "message_too_large",
                    "Message payload exceeds the allowed size.",
                )
                continue
            try:
                incoming = WebSocketMessage.model_validate(json.loads(raw_message))
            except (json.JSONDecodeError, ValidationError):
                await _send_error(
                    websocket, "", "invalid_message",
                    "Send a valid chat message event.",
                )
                continue
            request_id = str(incoming.request_id)
            if db.scalar(
                select(User.id).where(User.id == user.id).with_for_update()
            ) is None:
                db.rollback()
                await websocket.close(code=4401)
                return
            rate_cutoff = datetime.now(UTC) - timedelta(seconds=60)
            db.execute(
                delete(ChatRequestAttempt).where(
                    ChatRequestAttempt.user_id == user.id,
                    ChatRequestAttempt.attempted_at < rate_cutoff,
                )
            )
            recent_message_count = int(
                db.scalar(
                    select(func.count(ChatRequestAttempt.id))
                    .where(
                        ChatRequestAttempt.user_id == user.id,
                        ChatRequestAttempt.attempted_at >= rate_cutoff,
                    )
                )
                or 0
            )
            if recent_message_count >= MAX_MESSAGES_PER_MINUTE:
                db.rollback()
                await _send_error(
                    websocket, request_id, "rate_limited",
                    "Message limit reached. Please wait before trying again.",
                )
                continue
            try:
                _validate_filters(db, user, incoming.filters)
            except HTTPException as error:
                db.rollback()
                await _send_error(
                    websocket, request_id, "invalid_filter", str(error.detail)
                )
                continue

            locked_conversation = db.scalar(
                select(ChatConversation)
                .where(
                    ChatConversation.id == conversation_id,
                    ChatConversation.user_id == user.id,
                )
                .with_for_update()
            )
            if locked_conversation is None:
                db.rollback()
                await _send_error(
                    websocket, request_id, "conversation_not_found",
                    "Conversation not found.",
                )
                continue
            conversation = locked_conversation

            user_message = db.scalar(
                select(ChatMessage).where(
                    ChatMessage.conversation_id == conversation.id,
                    ChatMessage.request_id == request_id,
                    ChatMessage.role == "user",
                )
            )
            filters_json = incoming.filters.model_dump(mode="json")
            if user_message is not None and (
                user_message.content != incoming.content
                or (user_message.metadata_json or {}).get("filters") != filters_json
            ):
                db.rollback()
                await _send_error(
                    websocket, request_id, "request_id_conflict",
                    "This request ID was already used for a different message or filter set.",
                )
                continue

            assistant_message = db.scalar(
                select(ChatMessage).where(
                    ChatMessage.conversation_id == conversation.id,
                    ChatMessage.request_id == request_id,
                    ChatMessage.role == "assistant",
                )
            )
            if assistant_message is not None:
                await _send_answer(websocket, request_id, assistant_message.content)
                db.rollback()
                continue

            message_metadata = (
                (user_message.metadata_json or {}) if user_message else {}
            )
            started_at = message_metadata.get("started_at")
            if (
                message_metadata.get("status") == "pending"
                and isinstance(started_at, (int, float))
                and time() - started_at
                <= settings.chat_llm_timeout_seconds + PENDING_GRACE_SECONDS
            ):
                db.rollback()
                await _send_error(
                    websocket, request_id, "request_in_progress",
                    "This request is still processing. Retry after it completes.",
                )
                continue

            started_at = time()
            db.add(
                ChatRequestAttempt(user_id=user.id, attempted_at=datetime.now(UTC))
            )
            if user_message is None:
                user_message = ChatMessage(
                    conversation_id=conversation.id,
                    request_id=request_id,
                    role="user",
                    content=incoming.content,
                    metadata_json={
                        "filters": filters_json,
                        "status": "pending",
                        "started_at": started_at,
                    },
                )
                db.add(user_message)
                if conversation.title == "New conversation":
                    conversation.title = incoming.content.strip()[:117] or "New conversation"
                conversation.updated_at = datetime.now(UTC)
            else:
                user_message.metadata_json = {
                    **message_metadata,
                    "status": "pending",
                    "started_at": started_at,
                }
            conversation.updated_at = datetime.now(UTC)
            db.commit()

            try:
                answer, metadata = await SQLAgent(_client()).answer(
                    db, user, incoming.content, incoming.filters
                )
            except (LLMProviderError, SQLAgentError, HTTPException, SQLAlchemyError) as error:
                db.rollback()
                if not isinstance(error, SQLAlchemyError):
                    failed_user_message = db.scalar(
                        select(ChatMessage).where(
                            ChatMessage.conversation_id == conversation_id,
                            ChatMessage.request_id == request_id,
                            ChatMessage.role == "user",
                        )
                    )
                    if failed_user_message is not None:
                        failed_user_message.metadata_json = {
                            **(failed_user_message.metadata_json or {}),
                            "status": "failed",
                        }
                        db.commit()
                code = "provider_error" if isinstance(error, LLMProviderError) else "analytics_error"
                if isinstance(error, HTTPException):
                    message = str(error.detail)
                elif isinstance(error, SQLAlchemyError):
                    message = "The analytics query failed. Please try again."
                else:
                    message = str(error)
                await _send_error(websocket, request_id, code, message)
                continue

            user_message.metadata_json = {
                **(user_message.metadata_json or {}),
                "status": "completed",
            }
            db.add(
                ChatMessage(
                    conversation_id=conversation.id,
                    request_id=request_id,
                    role="assistant",
                    content=answer,
                    metadata_json=metadata,
                )
            )
            conversation.updated_at = datetime.now(UTC)
            db.commit()
            await _send_answer(websocket, request_id, answer)
