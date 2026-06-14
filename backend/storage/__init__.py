"""
持久化层 —— Redis 状态存储 + PostgreSQL 结果归档。

包含：
- RedisStateStore：任务元信息、事件流、短期记忆
- PostgresResultStore：最终方案、Markdown 报告、Agent 参与分析
"""
