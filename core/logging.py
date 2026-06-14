"""
结构化日志 —— 基于 Loguru，JSON 格式输出。

用法: from core.logging import logger
"""
import sys
from pathlib import Path
from loguru import logger

# 清除默认 handler
logger.remove()

# 控制台：彩色、开发友好
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> | {message}",
    level="DEBUG",
    colorize=True,
)

# 确保日志目录存在
log_dir = Path(__file__).resolve().parents[1] / "backend" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

# 文件：JSON 格式，生产可检索
logger.add(
    str(log_dir / "agent_{time:YYYY-MM-DD}.json"),
    format="{time} {level} {name} {function} {line} {message}",
    serialize=True,
    rotation="10 MB",
    retention="7 days",
    level="INFO",
)

__all__ = ["logger"]