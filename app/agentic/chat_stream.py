from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .models import ChatMessage, TokenUsage

RetryEmitter = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ChatDelta:
    content: str


@dataclass(frozen=True, slots=True)
class ChatComplete:
    message: ChatMessage
    usage: TokenUsage | None


StreamChunk = ChatDelta | ChatComplete | TokenUsage
