"""
ChatSession 数据模型 + Redis 存储。

提供：
- ChatSession: 会话数据模型（对话历史 + 累积事实）
- ChatSessionStore: Redis 持久化实现
- Redis 不可用时自动降级为内存模式
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# ======================== 数据模型 ========================

@dataclass
class ChatMessage:
    """单条对话消息。"""
    role: str              # "user" | "assistant" | "system"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    # metadata 可包含: intent, extracted_facts, task_id, confidence 等

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChatMessage":
        return cls(
            role=d.get("role", "user"),
            content=d.get("content", ""),
            timestamp=d.get("timestamp", ""),
            metadata=d.get("metadata", {}),
        )


@dataclass
class ChatSession:
    """会话数据模型。"""
    session_id: str
    user_id: str = "anonymous"
    messages: List[ChatMessage] = field(default_factory=list)
    accumulated_facts: Dict[str, Any] = field(default_factory=dict)
    active_task_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def add_message(self, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> ChatMessage:
        msg = ChatMessage(role=role, content=content, metadata=metadata or {})
        self.messages.append(msg)
        self.updated_at = datetime.now().isoformat()
        return msg

    def merge_facts(self, new_facts: Dict[str, Any]) -> Dict[str, Any]:
        """合并新提取的事实到累积事实。非空值覆盖，None 不覆盖。"""
        for key, value in new_facts.items():
            if key == "missing_fields":
                continue
            if value is not None and value != "" and value != []:
                self.accumulated_facts[key] = value
        self.updated_at = datetime.now().isoformat()
        return self.accumulated_facts

    def get_missing_fields(self) -> List[str]:
        """检查还有哪些必要字段缺失。"""
        required = ["destination", "start_date", "end_date"]
        missing = []
        for field in required:
            if not self.accumulated_facts.get(field):
                missing.append(field)
        # 如果没有 departure，不影响规划（只是不启用交通 Agent）
        return missing

    def is_ready_for_plan(self) -> bool:
        """信息是否足够创建计划。"""
        return len(self.get_missing_fields()) == 0

    def get_recent_messages(self, n: int = 10) -> List[ChatMessage]:
        """获取最近 n 条消息。"""
        return self.messages[-n:]

    def get_chat_history_text(self, max_messages: int = 10) -> str:
        """获取格式化的对话历史文本。"""
        lines = []
        for msg in self.get_recent_messages(max_messages):
            role_label = {"user": "用户", "assistant": "旅小智", "system": "系统"}.get(msg.role, msg.role)
            lines.append(f"{role_label}: {msg.content}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "messages": [m.to_dict() for m in self.messages],
            "accumulated_facts": self.accumulated_facts,
            "active_task_id": self.active_task_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChatSession":
        return cls(
            session_id=d.get("session_id", ""),
            user_id=d.get("user_id", "anonymous"),
            messages=[ChatMessage.from_dict(m) for m in d.get("messages", [])],
            accumulated_facts=d.get("accumulated_facts", {}),
            active_task_id=d.get("active_task_id"),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )


# ======================== Redis 存储 ========================

class ChatSessionStore:
    """
    ChatSession 持久化存储。

    优先使用 Redis，不可用时降级为内存字典（重启丢失）。
    """

    SESSION_PREFIX = "chat:session:"
    DEFAULT_TTL = 86400  # 24 小时

    def __init__(self, logger=None):
        self._logger = logger
        self._redis = None
        self._fallback: Dict[str, dict] = {}  # 内存降级
        self._redis_available = False
        self._try_connect_redis()

    def _try_connect_redis(self) -> None:
        """尝试连接 Redis。"""
        try:
            import redis
            from core.config import settings
            r = redis.from_url(settings.redis_url, socket_connect_timeout=3, decode_responses=True)
            r.ping()
            self._redis = r
            self._redis_available = True
            if self._logger:
                self._logger.info("ChatSessionStore: Redis 连接成功")
        except Exception as e:
            self._redis_available = False
            if self._logger:
                self._logger.warning(f"ChatSessionStore: Redis 不可用，降级为内存模式 ({e})")

    def _log(self, msg: str) -> None:
        if self._logger:
            self._logger.info(msg)

    # ── CRUD ──

    def create_session(self, user_id: str = "anonymous") -> ChatSession:
        """创建新会话。"""
        session = ChatSession(
            session_id=f"sess_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
        )
        self._save(session)
        self._log(f"ChatSessionStore: 创建会话 {session.session_id}")
        return session

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        """获取会话。"""
        data = self._load(session_id)
        if data is None:
            return None
        return ChatSession.from_dict(data)

    def update_session(self, session: ChatSession) -> None:
        """更新会话。"""
        session.updated_at = datetime.now().isoformat()
        self._save(session)

    def delete_session(self, session_id: str) -> bool:
        """删除会话。"""
        if self._redis_available and self._redis:
            self._redis.delete(f"{self.SESSION_PREFIX}{session_id}")
        self._fallback.pop(session_id, None)
        return True

    # ── 内部 ──

    def _save(self, session: ChatSession) -> None:
        data = json.dumps(session.to_dict(), ensure_ascii=False)
        if self._redis_available and self._redis:
            self._redis.setex(
                f"{self.SESSION_PREFIX}{session.session_id}",
                self.DEFAULT_TTL,
                data,
            )
        else:
            self._fallback[session.session_id] = session.to_dict()

    def _load(self, session_id: str) -> Optional[dict]:
        if self._redis_available and self._redis:
            raw = self._redis.get(f"{self.SESSION_PREFIX}{session_id}")
            if raw:
                return json.loads(raw)
        data = self._fallback.get(session_id)
        return data
