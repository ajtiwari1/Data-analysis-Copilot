import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  request,
  websocketUrl,
  type ChatConversation,
  type ChatFilters,
  type ChatMessage,
  type ChatSocketEvent,
} from "./api";

interface ChatPanelProps {
  filters: ChatFilters;
}

interface DraftMessage {
  content: string;
  requestId: string;
  filters: ChatFilters;
}

const suggestions = [
  "Which products earned the most this month?",
  "How did sales change compared with the previous period?",
  "Which site had the highest average order value?",
];

function newRequestId(): string {
  return crypto.randomUUID();
}

function isChatFilters(value: unknown): value is ChatFilters {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.start_date === "string" &&
    typeof candidate.end_date === "string" &&
    (candidate.site_id === null || typeof candidate.site_id === "number") &&
    (candidate.product_id === null || typeof candidate.product_id === "number")
  );
}

function messageFilters(
  message: ChatMessage,
  messages: ChatMessage[],
): ChatFilters | null {
  const ownFilters = message.metadata_json?.filters;
  const userMessage =
    message.role === "user"
      ? message
      : messages.find(
          (item) => item.request_id === message.request_id && item.role === "user",
        );
  const filters = ownFilters ?? userMessage?.metadata_json?.filters;
  return isChatFilters(filters) ? filters : null;
}

export function ChatPanel({ filters }: ChatPanelProps) {
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [hasEarlierMessages, setHasEarlierMessages] = useState(false);
  const [draft, setDraft] = useState("");
  const [connected, setConnected] = useState(false);
  const [socketGeneration, setSocketGeneration] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [failed, setFailed] = useState<DraftMessage | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const bootstrapRef = useRef<Promise<ChatConversation[]> | null>(null);

  useEffect(() => {
    let active = true;
    if (!bootstrapRef.current) {
      bootstrapRef.current = request<ChatConversation[]>("/api/chat/conversations")
        .then(async (items) => {
          if (items.length) return items;
          const created = await request<ChatConversation>("/api/chat/conversations", {
            method: "POST",
            body: JSON.stringify({ title: "New conversation" }),
          });
          return [created];
        });
    }
    bootstrapRef.current
      .then((items) => {
        if (!active) return;
        setConversations(items);
        setConversationId(items[0]?.id ?? null);
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(cause instanceof Error ? cause.message : "Unable to load chat.");
        }
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (conversationId === null) return;
    let active = true;
    setMessages([]);
    setError("");
    request<ChatMessage[]>(
      `/api/chat/conversations/${conversationId}/messages?limit=50`,
    )
      .then((items) => {
        if (active) {
          setMessages(items);
          setHasEarlierMessages(items.length === 50);
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(cause instanceof Error ? cause.message : "Unable to load messages.");
        }
      });

    const socket = new WebSocket(
      websocketUrl(`/api/chat/conversations/${conversationId}/ws`),
    );
    socketRef.current = socket;
    socket.onopen = () => {
      if (active) {
        setConnected(true);
        setError("");
      }
    };
    socket.onmessage = (messageEvent: MessageEvent<string>) => {
      let event: ChatSocketEvent;
      try {
        event = JSON.parse(messageEvent.data) as ChatSocketEvent;
      } catch {
        if (active) setError("Received an invalid response from chat.");
        return;
      }
      if (!active) return;
      if (event.type === "assistant.delta") {
        setMessages((existing) => {
          const existingIndex = existing.findIndex(
            (message) =>
              message.request_id === event.request_id &&
              message.role === "assistant",
          );
          if (existingIndex >= 0) {
            return existing.map((message, index) =>
              index === existingIndex
                ? { ...message, content: message.content + (event.content ?? "") }
                : message,
            );
          }
          return [
            ...existing,
            {
              id: Date.now(),
              request_id: event.request_id,
              role: "assistant",
              content: event.content ?? "",
              metadata_json: null,
              created_at: new Date().toISOString(),
            },
          ];
        });
      } else if (event.type === "assistant.done") {
        setBusy(false);
        setFailed(null);
      } else {
        setBusy(false);
        setError(event.message ?? "The chat request failed.");
        setFailed((current) =>
          current?.requestId === event.request_id ? current : null,
        );
      }
    };
    socket.onerror = () => {
      if (active) setError("Chat connection failed. Please reconnect and try again.");
    };
    socket.onclose = () => {
      if (active) {
        setConnected(false);
        setBusy(false);
        setError((current) => current || "Chat connection closed. Reconnect to continue.");
      }
    };

    return () => {
      active = false;
      socket.close();
      if (socketRef.current === socket) socketRef.current = null;
    };
  }, [conversationId, socketGeneration]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  async function createConversation() {
    setError("");
    try {
      const created = await request<ChatConversation>("/api/chat/conversations", {
        method: "POST",
        body: JSON.stringify({ title: "New conversation" }),
      });
      setConversations((current) => [created, ...current]);
      setConversationId(created.id);
      setFailed(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to create a conversation.");
    }
  }

  async function deleteCurrentConversation() {
    if (conversationId === null) return;
    setError("");
    try {
      await request<void>(`/api/chat/conversations/${conversationId}`, {
        method: "DELETE",
      });
      const remaining = conversations.filter((item) => item.id !== conversationId);
      setConversations(remaining);
      if (remaining.length) {
        setConversationId(remaining[0].id);
      } else {
        const created = await request<ChatConversation>("/api/chat/conversations", {
          method: "POST",
          body: JSON.stringify({ title: "New conversation" }),
        });
        setConversations([created]);
        setConversationId(created.id);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to delete conversation.");
    }
  }

  async function loadEarlierMessages() {
    if (conversationId === null || messages.length === 0) return;
    const beforeId = messages[0].id;
    try {
      const earlier = await request<ChatMessage[]>(
        `/api/chat/conversations/${conversationId}/messages?limit=50&before_id=${beforeId}`,
      );
      setMessages((current) => [...earlier, ...current]);
      setHasEarlierMessages(earlier.length === 50);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load earlier messages.");
    }
  }

  function sendMessage(content: string, retry?: DraftMessage) {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN || busy) {
      setError("Chat is not connected yet. Please try again in a moment.");
      return;
    }
    const requestId = retry?.requestId ?? newRequestId();
    const selectedFilters = retry?.filters ?? filters;
    if (!retry) {
      const userMessage: ChatMessage = {
        id: Date.now(),
        request_id: requestId,
        role: "user",
        content,
        metadata_json: { filters: selectedFilters },
        created_at: new Date().toISOString(),
      };
      setMessages((current) => [...current, userMessage]);
      setConversations((current) =>
        current.map((conversation) =>
          conversation.id === conversationId &&
          conversation.title === "New conversation"
            ? { ...conversation, title: content.slice(0, 117) || "New conversation" }
            : conversation,
        ),
      );
    }
    setBusy(true);
    setError("");
    setFailed(null);
    setDraft("");
    const payload = {
      type: "message",
      request_id: requestId,
      content,
      filters: selectedFilters,
    };
    socket.send(JSON.stringify(payload));
    setFailed({ content, requestId, filters: selectedFilters });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = draft.trim();
    if (content) sendMessage(content);
  }

  return (
    <section className="chat-panel" aria-labelledby="chat-title">
      <header className="chat-header">
        <div>
          <p className="eyebrow">ANALYTICS ASSISTANT</p>
          <h2 id="chat-title">Ask about your sales</h2>
          <p className="chat-filter-note">
            Using dashboard filters: {filters.start_date} to {filters.end_date}
            {filters.site_id ? ` · site ${filters.site_id}` : " · all sites"}
            {filters.product_id ? ` · product ${filters.product_id}` : ""}
          </p>
        </div>
        <div className="chat-actions">
          <label className="visually-hidden" htmlFor="chat-conversations">
            Conversation
          </label>
          <select
            id="chat-conversations"
            value={conversationId ?? ""}
            onChange={(event) => setConversationId(Number(event.target.value))}
            disabled={!conversations.length}
          >
            {conversations.map((conversation) => (
              <option key={conversation.id} value={conversation.id}>
                {conversation.title}
              </option>
            ))}
          </select>
          <button className="button button-secondary" onClick={() => void createConversation()}>
            New chat
          </button>
          <button
            className="button button-secondary"
            onClick={() => void deleteCurrentConversation()}
            disabled={conversationId === null}
          >
            Delete
          </button>
        </div>
      </header>

      <div className="chat-transcript" role="log" aria-live="polite" aria-relevant="additions text">
        {hasEarlierMessages && (
          <button
            className="button button-secondary chat-load-earlier"
            onClick={() => void loadEarlierMessages()}
          >
            Load earlier messages
          </button>
        )}
        {messages.length === 0 && (
          <div className="chat-welcome">
            <p>Hi! I can help explore sales totals, product and site rankings, and period comparisons.</p>
            <div className="chat-suggestions" aria-label="Suggested questions">
              {suggestions.map((suggestion) => (
                <button
                  key={suggestion}
                  className="suggestion-button"
                  onClick={() => sendMessage(suggestion)}
                  disabled={!connected || busy}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((message) => {
          const usedFilters =
            message.role === "assistant" ? messageFilters(message, messages) : null;
          return (
            <article
              className={`chat-message chat-message-${message.role}`}
              key={`${message.request_id}-${message.role}`}
            >
              <span>{message.role === "assistant" ? "Assistant" : "You"}</span>
              <p>{message.content}</p>
              {usedFilters && (
                <small className="chat-message-context">
                  Filters: {usedFilters.start_date} to {usedFilters.end_date}
                  {usedFilters.site_id ? ` · site #${usedFilters.site_id}` : " · all sites"}
                  {usedFilters.product_id ? ` · product #${usedFilters.product_id}` : ""}
                </small>
              )}
            </article>
          );
        })}
        {busy && <p className="chat-status">Analyzing your sales data…</p>}
        <div ref={messagesEndRef} />
      </div>
      <div className="chat-footer">
        <p className="chat-connection" role="status">
          {connected ? "Connected" : "Connecting to chat…"}
        </p>
        {error && (
          <div className="chat-error" role="alert">
            <span>{error}</span>
            {!connected && conversationId !== null && (
              <button
                className="button button-secondary"
                onClick={() => setSocketGeneration((generation) => generation + 1)}
              >
                Reconnect
              </button>
            )}
            {failed && connected && (
              <button
                className="button button-secondary"
                onClick={() => sendMessage(failed.content, failed)}
              >
                Retry
              </button>
            )}
          </div>
        )}
        <form className="chat-composer" onSubmit={handleSubmit}>
          <label className="visually-hidden" htmlFor="chat-input">
            Ask a sales question
          </label>
          <textarea
            id="chat-input"
            value={draft}
            maxLength={4000}
            rows={2}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Ask about products, sites, or sales trends…"
            disabled={!connected || busy}
          />
          <button
            className="button button-primary"
            type="submit"
            disabled={!connected || busy || !draft.trim()}
          >
            Send
          </button>
        </form>
      </div>
    </section>
  );
}
