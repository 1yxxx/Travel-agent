"""
数据持久化层 —— Redis 状态存储 + PostgreSQL 结果归档。

设计原则（需求文档 §12）：
- Redis：热状态层（任务元信息、事件流、短期记忆），适合高频读写，TTL 自动过期
- PostgreSQL：冷归档层（最终方案、Markdown 报告、Agent 参与分析），适合长期存储和统计查询

两层存储的关系：
  Redis（热）──7天后过期──→  PostgreSQL（冷）──永久保留──→  审计/统计

优雅降级：
- Redis 不可用时：任务仍在内存中正常运行，只是不持久化
- PostgreSQL 不可用时：结果仍保存为本地 JSON/Markdown 文件

Python 新手提示：
- from __future__ import annotations 让类型注解可以延迟求值，避免循环导入
- @dataclass 是 Python 3.7+ 的数据类装饰器，自动生成 __init__/__repr__ 等方法
- psycopg 是 PostgreSQL 的 Python 驱动（psycopg2 的下一代）
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from redis import Redis
from redis.exceptions import RedisError
import psycopg
from psycopg.types.json import Json


# ======================== JSON 序列化工具函数 ========================

def _json_dumps(value: Any) -> str:
    """
    将 Python 对象序列化为 JSON 字符串。

    ensure_ascii=False：保留中文字符，不转义为 \\uXXXX
    default=str：对无法直接序列化的类型（如 datetime）转为字符串
    """
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_loads(value: Optional[str], default: Any) -> Any:
    """
    将 JSON 字符串反序列化为 Python 对象。

    安全处理：空值或解析失败时返回默认值，不抛异常。
    """
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


# ======================== Redis 配置 ========================

@dataclass
class RedisConfig:
    """
    Redis 连接配置。

    字段说明：
        host:            Redis 服务器地址（默认 127.0.0.1）
        port:            Redis 端口（默认 6379）
        db:              数据库编号（默认 0）
        password:        密码（可选）
        task_ttl_seconds: 任务数据过期时间（默认 604800 秒 = 7 天）
    """
    host: str
    port: int
    db: int
    password: str
    task_ttl_seconds: int


# ======================== Redis 状态存储 ========================

class RedisStateStore:
    """
    基于 Redis 的任务状态存储。

    职责：
    - 存储任务元信息（状态、进度、当前 Agent）
    - 存储请求/结果快照
    - 存储短期记忆
    - 存储事件流（使用 Redis Stream，支持按时间顺序消费）

    键命名规范（tp = trip planner 的缩写）：
        tp:task:{task_id}:meta              → Hash  (任务元信息)
        tp:task:{task_id}:request           → String(请求快照 JSON)
        tp:task:{task_id}:result            → String(结果快照 JSON)
        tp:task:{task_id}:short_term_memory → String(短期记忆 JSON)
        tp:task:{task_id}:events            → Stream(事件流)
    """

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        """
        初始化 Redis 状态存储。

        参数：
            logger: 日志记录器（可选，默认创建专用 logger）
        """
        self.logger = logger or logging.getLogger("redis_state_store")

        # 从环境变量读取 Redis 连接配置
        self.cfg = RedisConfig(
            host=os.getenv("REDIS_HOST", "127.0.0.1").strip(),
            port=int(os.getenv("REDIS_PORT", "6379").strip()),
            db=int(os.getenv("REDIS_DB", "0").strip()),
            password=os.getenv("REDIS_PASSWORD", "").strip(),
            task_ttl_seconds=int(
                os.getenv("REDIS_TASK_TTL_SECONDS", "604800").strip()
            ),
        )

        self._client: Optional[Redis] = None
        self.enabled: bool = False
        self._connect()  # 尝试建立连接

    def _connect(self) -> None:
        """
        尝试连接 Redis。

        连接失败时设置 enabled=False，后续所有操作都会跳过 Redis。
        这是优雅降级的关键：Redis 不可用时不影响核心功能。
        """
        try:
            self._client = Redis(
                host=self.cfg.host,
                port=self.cfg.port,
                db=self.cfg.db,
                password=self.cfg.password or None,
                decode_responses=True,       # 自动将 bytes 解码为 str
                socket_connect_timeout=3,    # 连接超时 3 秒
                socket_timeout=3,            # 读写超时 3 秒
            )
            self._client.ping()  # 发送 PING 命令测试连接
            self.enabled = True
            self.logger.info(
                f"[RedisStateStore] 已连接: {self.cfg.host}:{self.cfg.port}/{self.cfg.db}"
            )
        except Exception as exc:
            self._client = None
            self.enabled = False
            self.logger.warning(f"[RedisStateStore] 不可用，已禁用: {exc}")

    # ---- 键名生成（静态方法：不依赖实例状态） ----

    @staticmethod
    def _meta_key(task_id: str) -> str:
        """任务元信息的 Redis Key"""
        return f"tp:task:{task_id}:meta"

    @staticmethod
    def _request_key(task_id: str) -> str:
        """请求快照的 Redis Key"""
        return f"tp:task:{task_id}:request"

    @staticmethod
    def _result_key(task_id: str) -> str:
        """结果快照的 Redis Key"""
        return f"tp:task:{task_id}:result"

    @staticmethod
    def _memory_key(task_id: str) -> str:
        """短期记忆的 Redis Key"""
        return f"tp:task:{task_id}:short_term_memory"

    @staticmethod
    def _events_key(task_id: str) -> str:
        """事件流的 Redis Key"""
        return f"tp:task:{task_id}:events"

    def _expire_all(self, task_id: str) -> None:
        """
        为任务的所有 Key 设置过期时间（TTL）。

        这样 Redis 中的数据会在 7 天后自动清理，避免内存无限增长。
        """
        if not self.enabled or not self._client:
            return
        ttl = self.cfg.task_ttl_seconds
        self._client.expire(self._meta_key(task_id), ttl)
        self._client.expire(self._request_key(task_id), ttl)
        self._client.expire(self._result_key(task_id), ttl)
        self._client.expire(self._memory_key(task_id), ttl)
        self._client.expire(self._events_key(task_id), ttl)

    # ---- 公开方法 ----

    def upsert_task(self, task_id: str, task: Dict[str, Any]) -> None:
        """
        保存或更新任务状态到 Redis。

        同时写入两个 Key：
        - meta (Hash)：任务元信息（状态、进度、当前 Agent 等）
        - request (String)：原始请求的 JSON 快照
        - result (String)：规划结果的 JSON 快照

        参数：
            task_id: 任务唯一标识
            task:    任务状态字典（与 planning_tasks 中的格式一致）
        """
        if not self.enabled or not self._client:
            return
        try:
            # 构建元信息 Hash
            meta = {
                "task_id": task_id,
                "status": str(task.get("status", "")),
                "progress": str(task.get("progress", 0)),
                "current_agent": str(task.get("current_agent", "")),
                "message": str(task.get("message", "")),
                "created_at": str(task.get("created_at", "")),
                "updated_at": str(task.get("updated_at", "")),
                "result_file": str(task.get("result_file", "")),
                "result_markdown_file": str(task.get("result_markdown_file", "")),
            }
            # hset 写入 Hash 类型
            self._client.hset(self._meta_key(task_id), mapping=meta)

            # 写入请求快照（如果存在）
            if task.get("request") is not None:
                self._client.set(
                    self._request_key(task_id),
                    _json_dumps(task.get("request")),
                )

            # 写入结果快照（如果存在）
            if task.get("result") is not None:
                self._client.set(
                    self._result_key(task_id),
                    _json_dumps(task.get("result")),
                )

            # 设置过期时间
            self._expire_all(task_id)
        except RedisError as exc:
            self.logger.warning(
                f"[RedisStateStore] upsert_task 失败 task={task_id}: {exc}"
            )

    def append_event(self, task_id: str, event: Dict[str, Any]) -> None:
        """
        追加一条事件到 Redis Stream。

        Redis Stream 类似于 Kafka 的消息队列：
        - 每条消息有唯一的 ID（自动生成）
        - 按追加顺序排列，支持按时间范围查询
        - 这里用它来存储 SSE 事件的完整历史

        参数：
            task_id: 任务唯一标识
            event:   事件字典（包含 type、message、progress 等字段）
        """
        if not self.enabled or not self._client:
            return
        try:
            # 将事件数据转为字段-值对（Stream 要求 flat key-value）
            payload = {
                "seq": str(event.get("seq", "")),
                "type": str(event.get("type", "")),
                "message": str(event.get("message", "")),
                "timestamp": str(event.get("timestamp", "")),
                "progress": str(event.get("progress", "")),
                "agent": str(event.get("agent", "")),
                "status": str(event.get("status", "")),
                "data_json": _json_dumps(event.get("data", {})),
            }
            # xadd 追加到 Stream
            self._client.xadd(self._events_key(task_id), payload)
            # 设置 Stream 的过期时间
            self._client.expire(
                self._events_key(task_id),
                self.cfg.task_ttl_seconds,
            )
        except RedisError as exc:
            self.logger.warning(
                f"[RedisStateStore] append_event 失败 task={task_id}: {exc}"
            )

    def save_short_term_memory(self, task_id: str, memory: Dict[str, Any]) -> None:
        """
        保存短期记忆到 Redis。

        短期记忆包含：
        - 请求快照
        - Agent 执行状态
        - 汇总结果
        - 行程输出

        参数：
            task_id: 任务唯一标识
            memory:  短期记忆字典
        """
        if not self.enabled or not self._client:
            return
        try:
            self._client.set(
                self._memory_key(task_id),
                _json_dumps(memory),
            )
            self._client.expire(
                self._memory_key(task_id),
                self.cfg.task_ttl_seconds,
            )
            self.logger.info(
                f"[RedisStateStore] 短期记忆已保存 task={task_id}"
            )
        except RedisError as exc:
            self.logger.warning(
                f"[RedisStateStore] save_short_term_memory 失败 task={task_id}: {exc}"
            )

    def get_task_snapshot(self, task_id: str) -> Dict[str, Any]:
        """
        从 Redis 获取任务的完整快照。

        返回包含：元信息、请求、结果、短期记忆、事件列表。

        参数：
            task_id: 任务唯一标识

        返回：
            任务快照字典（Redis 不可用或任务不存在时返回空字典）
        """
        if not self.enabled or not self._client:
            return {}
        try:
            # 读取元信息 Hash
            meta = self._client.hgetall(self._meta_key(task_id))
            if not meta:
                return {}

            # 读取请求/结果/记忆
            request_json = self._client.get(self._request_key(task_id))
            result_json = self._client.get(self._result_key(task_id))
            memory_json = self._client.get(self._memory_key(task_id))

            # 读取事件 Stream（最近 200 条）
            events = self._client.xrange(
                self._events_key(task_id),
                min="-",     # 从最早开始
                max="+",     # 到最晚结束
                count=200,   # 最多 200 条
            )

            # 反序列化事件数据
            event_items: List[Dict[str, Any]] = []
            for _, fields in events:
                item = dict(fields)
                item["data"] = _json_loads(item.get("data_json"), {})
                item.pop("data_json", None)
                event_items.append(item)

            return {
                "meta": meta,
                "request": _json_loads(request_json, {}),
                "result": _json_loads(result_json, {}),
                "short_term_memory": _json_loads(memory_json, {}),
                "events": event_items,
            }
        except RedisError as exc:
            self.logger.warning(
                f"[RedisStateStore] get_task_snapshot 失败 task={task_id}: {exc}"
            )
            return {}


# ======================== PostgreSQL 配置 ========================

@dataclass
class PostgresConfig:
    """
    PostgreSQL 连接配置。

    字段说明：
        host:     数据库服务器地址
        port:     端口（默认 5432）
        user:     用户名
        password: 密码
        dbname:   数据库名
    """
    host: str
    port: int
    user: str
    password: str
    dbname: str


# ======================== PostgreSQL 结果存储 ========================

class PostgresResultStore:
    """
    基于 PostgreSQL 的最终结果归档存储。

    职责：
    - 存储每次规划的最终结果（JSON + Markdown）
    - 记录 Agent 参与情况
    - 支持后续检索和统计分析

    表结构（travel_planning_results）：
        task_id:                 任务唯一标识（UNIQUE）
        status:                  任务状态
        destination:             目的地
        request_json:            原始请求（JSONB）
        result_json:             规划结果（JSONB）
        short_term_memory_json:  短期记忆（JSONB）
        final_plan_markdown:     最终 Markdown 方案
        agent_participation_json: Agent 参与分析（JSONB）
        planning_complete:       是否完整完成
        missing_agents:          缺失的 Agent 列表（JSONB）
        created_at / updated_at: 时间戳
    """

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        """
        初始化 PostgreSQL 结果存储。

        参数：
            logger: 日志记录器
        """
        self.logger = logger or logging.getLogger("postgres_result_store")

        # 从环境变量读取配置
        self.cfg = PostgresConfig(
            host=os.getenv("POSTGRES_HOST", "127.0.0.1").strip(),
            port=int(os.getenv("POSTGRES_PORT", "5432").strip()),
            user=os.getenv("POSTGRES_USER", "").strip(),
            password=os.getenv("POSTGRES_PASSWORD", "").strip(),
            dbname=os.getenv("POSTGRES_DB", "postgres").strip(),
        )

        # 只在配置完整时启用
        self.enabled = all([
            self.cfg.host,
            self.cfg.port,
            self.cfg.user,
            self.cfg.dbname,
        ])

        if self.enabled:
            self._ensure_table()  # 自动创建表和索引
        else:
            self.logger.info(
                "[PostgresResultStore] 未配置，已禁用"
            )

    def _connect(self) -> psycopg.Connection:
        """
        创建 PostgreSQL 数据库连接。

        使用 psycopg（psycopg3），比 psycopg2 更现代的驱动。
        """
        return psycopg.connect(
            host=self.cfg.host,
            port=self.cfg.port,
            user=self.cfg.user,
            password=self.cfg.password,
            dbname=self.cfg.dbname,
            connect_timeout=5,
        )

    def _ensure_table(self) -> None:
        """
        确保数据库表存在（自动建表）。

        如果表不存在则创建，如果已存在则跳过（IF NOT EXISTS）。
        同时创建 task_id 和 created_at 的索引，加速查询。
        还处理了旧版本缺少 agent_participation_json 列的兼容性问题。
        """
        if not self.enabled:
            return
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    # 创建主表
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS travel_planning_results (
                            id BIGSERIAL PRIMARY KEY,
                            task_id TEXT UNIQUE NOT NULL,
                            status TEXT NOT NULL,
                            destination TEXT,
                            request_json JSONB NOT NULL,
                            result_json JSONB NOT NULL,
                            short_term_memory_json JSONB,
                            final_plan_markdown TEXT,
                            agent_participation_json JSONB,
                            planning_complete BOOLEAN DEFAULT FALSE,
                            missing_agents JSONB,
                            result_file TEXT,
                            result_markdown_file TEXT,
                            created_at TIMESTAMPTZ DEFAULT NOW(),
                            updated_at TIMESTAMPTZ DEFAULT NOW()
                        )
                    """)

                    # 创建索引：按 task_id 查询
                    cur.execute(
                        "CREATE INDEX IF NOT EXISTS idx_travel_planning_results_task_id "
                        "ON travel_planning_results(task_id)"
                    )

                    # 创建索引：按创建时间倒序（用于列表查询）
                    cur.execute(
                        "CREATE INDEX IF NOT EXISTS idx_travel_planning_results_created_at "
                        "ON travel_planning_results(created_at DESC)"
                    )

                    # 向后兼容：为旧版本数据库添加缺失的列
                    cur.execute(
                        "ALTER TABLE travel_planning_results "
                        "ADD COLUMN IF NOT EXISTS agent_participation_json JSONB"
                    )

            self.logger.info(
                f"[PostgresResultStore] 已连接并确保表存在: "
                f"{self.cfg.host}:{self.cfg.port}/{self.cfg.dbname}"
            )
        except Exception as exc:
            self.enabled = False
            self.logger.warning(
                f"[PostgresResultStore] 连接失败，已禁用: {exc}"
            )

    def upsert_result(
        self,
        task_id: str,
        request: Dict[str, Any],
        result: Dict[str, Any],
        *,
        status: str,
        result_file: str,
        result_markdown_file: str,
        final_plan_markdown: str = "",
        missing_agents_override: Optional[List[str]] = None,
        agent_participation: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        插入或更新规划结果到 PostgreSQL。

        使用 ON CONFLICT ... DO UPDATE（UPSERT）语义：
        - 如果 task_id 不存在 → INSERT 新行
        - 如果 task_id 已存在 → UPDATE 现有行

        参数：
            task_id:                 任务唯一标识
            request:                 原始请求字典
            result:                  规划结果字典
            status:                  任务状态
            result_file:             JSON 结果文件名
            result_markdown_file:    Markdown 结果文件名
            final_plan_markdown:     最终方案 Markdown 文本
            missing_agents_override: 覆盖的缺失 Agent 列表
            agent_participation:     Agent 参与分析
        """
        if not self.enabled:
            return

        # 从结果中提取各字段
        travel_plan = (
            result.get("travel_plan", {})
            if isinstance(result, dict)
            else {}
        )
        destination = str(
            travel_plan.get("destination", request.get("destination", ""))
        )
        short_term_memory = result.get("short_term_memory", {})
        final_plan_text = str(
            final_plan_markdown or travel_plan.get("final_plan", "")
        ).strip()
        planning_complete = bool(result.get("planning_complete", False))
        missing_agents = (
            missing_agents_override
            if isinstance(missing_agents_override, list)
            else result.get("missing_agents", [])
        )
        participation = (
            agent_participation
            if isinstance(agent_participation, dict)
            else result.get("agent_participation", {})
        )

        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    # UPSERT：ON CONFLICT (task_id) DO UPDATE
                    cur.execute(
                        """
                        INSERT INTO travel_planning_results (
                            task_id, status, destination,
                            request_json, result_json,
                            short_term_memory_json, final_plan_markdown,
                            agent_participation_json, planning_complete,
                            missing_agents, result_file, result_markdown_file,
                            created_at, updated_at
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, NOW(), NOW()
                        )
                        ON CONFLICT (task_id) DO UPDATE SET
                            status = EXCLUDED.status,
                            destination = EXCLUDED.destination,
                            request_json = EXCLUDED.request_json,
                            result_json = EXCLUDED.result_json,
                            short_term_memory_json = EXCLUDED.short_term_memory_json,
                            final_plan_markdown = EXCLUDED.final_plan_markdown,
                            agent_participation_json = EXCLUDED.agent_participation_json,
                            planning_complete = EXCLUDED.planning_complete,
                            missing_agents = EXCLUDED.missing_agents,
                            result_file = EXCLUDED.result_file,
                            result_markdown_file = EXCLUDED.result_markdown_file,
                            updated_at = NOW()
                        """,
                        (
                            task_id,
                            status,
                            destination,
                            Json(request),        # psycopg 的 Json() 自动序列化
                            Json(result),
                            Json(short_term_memory if isinstance(short_term_memory, dict) else {}),
                            final_plan_text,
                            Json(participation if isinstance(participation, dict) else {}),
                            planning_complete,
                            Json(missing_agents if isinstance(missing_agents, list) else []),
                            result_file,
                            result_markdown_file,
                        ),
                    )
            self.logger.info(
                f"[PostgresResultStore] 结果已保存 task={task_id}"
            )
        except Exception as exc:
            self.logger.warning(
                f"[PostgresResultStore] upsert_result 失败 task={task_id}: {exc}"
            )

    def get_result(self, task_id: str) -> Dict[str, Any]:
        """
        从 PostgreSQL 查询任务结果。

        参数：
            task_id: 任务唯一标识

        返回：
            结果字典（任务不存在时返回空字典）
        """
        if not self.enabled:
            return {}
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT task_id, status, destination,
                               request_json, result_json,
                               short_term_memory_json, final_plan_markdown,
                               agent_participation_json,
                               planning_complete, missing_agents,
                               result_file, result_markdown_file,
                               created_at, updated_at
                        FROM travel_planning_results
                        WHERE task_id = %s
                        """,
                        (task_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return {}

            # 按列位置映射为字典
            return {
                "task_id": row[0],
                "status": row[1],
                "destination": row[2],
                "request_json": row[3],
                "result_json": row[4],
                "short_term_memory_json": row[5],
                "final_plan_markdown": row[6],
                "agent_participation_json": row[7],
                "planning_complete": row[8],
                "missing_agents": row[9],
                "result_file": row[10],
                "result_markdown_file": row[11],
                "created_at": str(row[12]),
                "updated_at": str(row[13]),
            }
        except Exception as exc:
            self.logger.warning(
                f"[PostgresResultStore] get_result 失败 task={task_id}: {exc}"
            )
            return {}
