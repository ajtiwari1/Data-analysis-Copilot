"""Provider-neutral LLM clients and provider adapters."""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
import json
from typing import Any

import httpx


class LLMProviderError(RuntimeError):
    """A safe, user-facing error from provider configuration or transport."""


@dataclass(frozen=True)
class LLMCapabilities:
    streaming: bool
    tool_calling: bool


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str | None
    api_key: str | None
    base_url: str | None
    timeout_seconds: float
    max_tokens: int


class LLMClient:
    provider = ""
    capabilities = LLMCapabilities(streaming=True, tool_calling=False)

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.model = config.model or self.default_model

    @property
    def default_model(self) -> str:
        raise NotImplementedError

    def _headers(self) -> dict[str, str]:
        raise NotImplementedError

    def _url(self, _stream: bool) -> str:
        raise NotImplementedError

    def _body(
        self, _messages: Sequence[dict[str, str]], _stream: bool
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _extract(self, _data: dict[str, Any]) -> str:
        raise NotImplementedError

    def _extract_stream(self, _data: dict[str, Any]) -> str:
        raise NotImplementedError

    async def complete(self, messages: Sequence[dict[str, str]]) -> str:
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                body = self._body(messages, False)
                response = await client.post(
                    self._url(False),
                    headers=self._headers(),
                    json=body,
                )
                response.raise_for_status()
                return self._extract(response.json())
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
            raise LLMProviderError(
                f"The configured {self.provider} provider could not complete the request."
            ) from error

    async def stream(self, messages: Sequence[dict[str, str]]) -> AsyncIterator[str]:
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                body = self._body(messages, True)
                async with client.stream(
                    "POST",
                    self._url(True),
                    headers=self._headers(),
                    json=body,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        chunk = self._parse_stream_line(line)
                        if chunk:
                            yield chunk
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
            raise LLMProviderError(
                f"The configured {self.provider} provider stream failed."
            ) from error

    def _parse_stream_line(self, line: str) -> str:
        if not line:
            return ""
        if self.provider == "ollama":
            data = json.loads(line)
            return str(data.get("message", {}).get("content", ""))
        if not line.startswith("data:"):
            return ""
        payload = line[5:].strip()
        if payload == "[DONE]":
            return ""
        data = json.loads(payload)
        return self._extract_stream(data)


class OpenAIClient(LLMClient):
    provider = "openai"

    @property
    def default_model(self) -> str:
        return "gpt-4o-mini"

    def _headers(self) -> dict[str, str]:
        if not self.config.api_key:
            raise LLMProviderError("CHAT_OPENAI_API_KEY is required for the OpenAI provider.")
        return {"Authorization": f"Bearer {self.config.api_key}"}

    def _url(self, _stream: bool) -> str:
        return f"{(self.config.base_url or 'https://api.openai.com/v1').rstrip('/')}/chat/completions"

    def _body(self, messages: Sequence[dict[str, str]], stream: bool) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": list(messages),
            "max_tokens": self.config.max_tokens,
            "stream": stream,
        }

    def _extract(self, data: dict[str, Any]) -> str:
        return str(data["choices"][0]["message"]["content"])

    def _extract_stream(self, data: dict[str, Any]) -> str:
        return str(data.get("choices", [{}])[0].get("delta", {}).get("content", ""))


class AnthropicClient(LLMClient):
    provider = "anthropic"

    @property
    def default_model(self) -> str:
        return "claude-3-5-haiku-latest"

    def _headers(self) -> dict[str, str]:
        if not self.config.api_key:
            raise LLMProviderError("CHAT_ANTHROPIC_API_KEY is required for Anthropic.")
        return {"x-api-key": self.config.api_key, "anthropic-version": "2023-06-01"}

    def _url(self, _stream: bool) -> str:
        return f"{(self.config.base_url or 'https://api.anthropic.com/v1').rstrip('/')}/messages"

    def _body(self, messages: Sequence[dict[str, str]], stream: bool) -> dict[str, Any]:
        system = "\n".join(item["content"] for item in messages if item["role"] == "system")
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.config.max_tokens,
            "messages": [
                {"role": item["role"], "content": item["content"]}
                for item in messages
                if item["role"] != "system"
            ],
            "stream": stream,
        }
        if system:
            body["system"] = system
        return body

    def _extract(self, data: dict[str, Any]) -> str:
        return "".join(str(block.get("text", "")) for block in data["content"])

    def _extract_stream(self, data: dict[str, Any]) -> str:
        delta = data.get("delta", {})
        return str(delta.get("text", "")) if delta.get("type") == "text_delta" else ""

    def _parse_stream_line(self, line: str) -> str:
        if line.startswith("data:"):
            return self._extract_stream(json.loads(line[5:].strip()))
        return ""


class GeminiClient(LLMClient):
    provider = "gemini"

    @property
    def default_model(self) -> str:
        return "gemini-2.0-flash"

    def _headers(self) -> dict[str, str]:
        if not self.config.api_key:
            raise LLMProviderError("CHAT_GEMINI_API_KEY is required for Gemini.")
        return {"x-goog-api-key": self.config.api_key}

    def _url(self, stream: bool) -> str:
        root = (self.config.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        action = "streamGenerateContent?alt=sse" if stream else "generateContent"
        return f"{root}/models/{self.model}:{action}"

    def _body(
        self, messages: Sequence[dict[str, str]], _stream: bool
    ) -> dict[str, Any]:
        system = "\n".join(item["content"] for item in messages if item["role"] == "system")
        contents = [
            {
                "role": "model" if item["role"] == "assistant" else "user",
                "parts": [{"text": item["content"]}],
            }
            for item in messages
            if item["role"] != "system"
        ]
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": self.config.max_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return body

    def _extract(self, data: dict[str, Any]) -> str:
        return "".join(
            str(part.get("text", ""))
            for part in data["candidates"][0]["content"]["parts"]
        )

    def _extract_stream(self, data: dict[str, Any]) -> str:
        return self._extract(data)


class OllamaClient(LLMClient):
    provider = "ollama"

    @property
    def default_model(self) -> str:
        return "llama3.2"

    def _headers(self) -> dict[str, str]:
        return {}

    def _url(self, _stream: bool) -> str:
        return f"{(self.config.base_url or 'http://localhost:11434').rstrip('/')}/api/chat"

    def _body(self, messages: Sequence[dict[str, str]], stream: bool) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": list(messages),
            "stream": stream,
            "options": {"num_predict": self.config.max_tokens},
        }

    def _extract(self, data: dict[str, Any]) -> str:
        return str(data["message"]["content"])

    def _extract_stream(self, data: dict[str, Any]) -> str:
        return self._extract(data)


def create_llm_client(config: LLMConfig) -> LLMClient:
    providers: dict[str, type[LLMClient]] = {
        "openai": OpenAIClient,
        "anthropic": AnthropicClient,
        "gemini": GeminiClient,
        "ollama": OllamaClient,
    }
    provider = config.provider.strip().lower()
    try:
        return providers[provider](config)
    except KeyError as error:
        raise LLMProviderError(
            "CHAT_LLM_PROVIDER must be openai, anthropic, gemini, or ollama."
        ) from error
