"""
结构化日志 —— 基于 Loguru，支持控制台彩色 + 文件 JSON 双输出。

设计原则（需求文档 §15.1）：
- 控制台：开发友好，彩色格式
- 文件：JSON 序列化，便于生产检索和 ELK 接入
- 轮转：按大小轮转（10 MB），保留 7 天

用法:
    from core.logging import logger
    logger.info("任务开始", task_id="abc123")
    logger.error("API 调用失败", provider="qweather", error=str(exc))
"""
import sys
from pathlib import Path
from loguru import logger

# 清除 Loguru 默认的 handler，避免重复输出
logger.remove()

# ======================== 控制台输出 ========================
# 彩色格式，适合开发调试
logger.add(
    sys.stderr,
    format=(
        "<green>{time:HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan> | "
        "{message}"
    ),
    level="DEBUG",
    colorize=True,
)

# ======================== 文件输出 ========================
# 确保日志目录存在
log_dir = Path(__file__).resolve().parents[1] / "backend" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

# JSON 序列化格式，生产环境可被 ELK/Logstash 消费
logger.add(
    str(log_dir / "agent_{time:YYYY-MM-DD}.json"),
    format="{time} {level} {name} {function} {line} {message}",
    serialize=True,        # JSON 序列化
    rotation="10 MB",      # 单文件 10MB 后轮转
    retention="7 days",    # 保留最近 7 天的日志
    level="INFO",           # 文件只记录 INFO 及以上
)

__all__ = ["logger"]
