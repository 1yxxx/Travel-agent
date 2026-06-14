#!/usr/bin/env python3
"""
TripAI 环境校验脚本 —— 检查所有数据源和服务是否就绪。

用法:
  python scripts/validate_env.py          # 检查所有
  python scripts/validate_env.py --quick  # 仅检查 API Key
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# 确保项目根在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def check_env_var(name: str) -> Tuple[bool, str]:
    """检查环境变量是否已设置。"""
    value = os.getenv(name, "").strip()
    if value and value != f"sk-your-{name.lower().replace('_', '-')}-here":
        return True, f"✅ {name} = {value[:12]}..."
    return False, f"❌ {name} 未配置或为占位符"


def check_llm() -> List[str]:
    """检查 LLM (DeepSeek) 配置。"""
    results = []
    results.append("=" * 50)
    results.append("1. LLM (DeepSeek)")
    results.append("=" * 50)

    ok, msg = check_env_var("OPENAI_API_KEY")
    results.append(msg)
    if not ok:
        results.append("   👉 获取: https://platform.deepseek.com → API Keys")

    base_url = os.getenv("OPENAI_BASE_URL", "")
    if "deepseek.com" in base_url:
        results.append(f"   ✅ OPENAI_BASE_URL = {base_url}")
    else:
        results.append(f"   ⚠️  OPENAI_BASE_URL = {base_url} (建议使用 https://api.deepseek.com)")

    model = os.getenv("OPENAI_MODEL", "")
    results.append(f"   ℹ️  OPENAI_MODEL = {model or 'deepseek-chat (默认)'}")
    return results


def check_real_apis() -> List[str]:
    """检查国内实时数据 API 配置。"""
    results = []
    results.append("")
    results.append("=" * 50)
    results.append("2. 国内实时数据 API")
    results.append("=" * 50)

    apis = [
        ("AMAP_API_KEY", "高德地图 (酒店/景点 POI)", "https://lbs.amap.com → 控制台 → 创建应用 → Web服务"),
        ("JUHE_FLIGHT_KEY", "聚合数据 (航班查询)", "https://www.juhe.cn → 航班订票查询"),
        ("JUHE_TRAIN_KEY", "聚合数据 (火车查询)", "https://www.juhe.cn → 火车订票查询"),
        ("QWEATHER_API_KEY", "和风天气 (天气预报)", "https://dev.qweather.com → 控制台 → 创建应用"),
    ]
    for var, name, guide in apis:
        ok, msg = check_env_var(var)
        results.append(f"   {msg} ← {name}")
        if not ok:
            results.append(f"      👉 获取: {guide}")
    return results


def check_chroma() -> List[str]:
    """检查 Chroma 本地知识库。"""
    results = []
    results.append("")
    results.append("=" * 50)
    results.append("3. Chroma 本地知识库 (RAG)")
    results.append("=" * 50)

    # 检查是否使用 Chroma Cloud
    cloud_ok = all([
        os.getenv("CHROMA_API_KEY", "").strip(),
        os.getenv("CHROMA_TENANT", "").strip(),
        os.getenv("CHROMA_DATABASE", "").strip(),
    ])

    if cloud_ok:
        results.append("   ✅ Chroma Cloud 模式已配置")
        return results

    # 本地模式：检查数据目录
    persist_dir = os.getenv("CHROMA_PERSIST_DIR", "./chroma_data")
    if not os.path.isabs(persist_dir):
        persist_dir = str(PROJECT_ROOT / persist_dir)

    persist_path = Path(persist_dir)
    if persist_path.exists():
        # 尝试连接并检查 collection
        try:
            import chromadb
            from chromadb.config import Settings

            client = chromadb.PersistentClient(
                path=str(persist_path),
                settings=Settings(anonymized_telemetry=False),
            )
            collection_name = os.getenv("CHROMA_COLLECTION", "travel_local_expert_knowledge")
            collection = client.get_or_create_collection(name=collection_name)
            count = collection.count()
            if count > 0:
                results.append(f"   ✅ 本地 ChromaDB 就绪: {count} 条知识记录")
            else:
                results.append(f"   ⚠️  本地 ChromaDB 已初始化但无数据")
                results.append(f"      👉 运行导入: python backend/scripts/ingest_local_knowledge_to_chroma.py")
        except Exception as e:
            results.append(f"   ⚠️  本地 ChromaDB 连接异常: {e}")
    else:
        results.append(f"   ℹ️  本地 ChromaDB 数据目录不存在: {persist_dir}")
        results.append(f"      👉 首次使用请运行: python backend/scripts/ingest_local_knowledge_to_chroma.py")

    # 检查知识源文件
    knowledge_dir = PROJECT_ROOT / "SimpleExample-knowledge-rag"
    if knowledge_dir.exists():
        md_files = list(knowledge_dir.glob("*.md"))
        results.append(f"   ℹ️  知识源文件: {len(md_files)} 个城市 ({', '.join(f.stem for f in md_files)})")
    return results


def check_redis() -> List[str]:
    """检查 Redis 连接。"""
    results = []
    results.append("")
    results.append("=" * 50)
    results.append("4. Redis (任务状态缓存)")
    results.append("=" * 50)

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis
        r = redis.from_url(redis_url)
        r.ping()
        results.append(f"   ✅ Redis 连接成功: {redis_url}")
    except ImportError:
        results.append(f"   ⚠️  redis-py 未安装，跳过连接测试")
        results.append(f"      URL: {redis_url}")
    except Exception as e:
        results.append(f"   ⚠️  Redis 不可用: {e}")
        results.append(f"      URL: {redis_url}")
        results.append(f"      👉 无 Redis 时系统自动回退到内存存储")
    return results


def check_postgres() -> List[str]:
    """检查 PostgreSQL 连接。"""
    results = []
    results.append("")
    results.append("=" * 50)
    results.append("5. PostgreSQL (结果归档)")
    results.append("=" * 50)

    pg_url = os.getenv("POSTGRES_URL", "")
    if not pg_url:
        results.append("   ℹ️  POSTGRES_URL 未配置")
        results.append("      👉 无 PostgreSQL 时系统自动回退到本地文件存储")
        return results

    try:
        import psycopg
        # 只尝试连接，不实际查询
        with psycopg.connect(pg_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            results.append(f"   ✅ PostgreSQL 连接成功")
    except ImportError:
        results.append(f"   ⚠️  psycopg 未安装，跳过连接测试")
    except Exception as e:
        results.append(f"   ⚠️  PostgreSQL 不可用: {e}")
        results.append(f"      👉 无 PostgreSQL 时系统自动回退到本地文件存储")
    return results


def check_weather_mcp() -> List[str]:
    """检查天气 MCP 模块。"""
    results = []
    results.append("")
    results.append("=" * 50)
    results.append("6. 天气 MCP 子进程")
    results.append("=" * 50)

    try:
        from backend.tools.weather_client_mcp import fetch_forecast_via_mcp
        results.append("   ✅ 天气 MCP 客户端可导入")
    except ImportError as e:
        results.append(f"   ⚠️  天气 MCP 客户端导入失败: {e}")
        results.append("      👉 天气将降级到 DuckDuckGo 搜索")

    # 检查 QWeather API (MCP 内部也需要)
    if os.getenv("QWEATHER_API_KEY", "").strip():
        results.append("   ✅ QWEATHER_API_KEY 已配置 (MCP 直连可用)")
    else:
        results.append("   ⚠️  QWEATHER_API_KEY 未配置")
        results.append("      👉 MCP 天气服务器将降级到 DuckDuckGo")
    return results


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="TripAI 环境校验")
    parser.add_argument("--quick", action="store_true", help="仅检查 API Key")
    args = parser.parse_args()

    print()
    print("🔍 TripAI 环境校验")
    print()

    # 加载 .env
    dotenv_path = PROJECT_ROOT / ".env"
    if dotenv_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(dotenv_path)
            print(f"📄 已加载: {dotenv_path}")
        except ImportError:
            # 手动解析 .env
            with open(dotenv_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and not os.getenv(key):
                            os.environ[key] = value
            print(f"📄 已加载: {dotenv_path} (手动解析)")
    else:
        print("⚠️  .env 文件不存在! 请在项目根目录创建 .env")
        print("   cp .env.deepseek .env  → 编辑填入 Key")

    all_checks = check_llm() + check_real_apis()

    if not args.quick:
        all_checks += check_chroma() + check_redis() + check_postgres() + check_weather_mcp()

    all_checks.append("")
    all_checks.append("=" * 50)
    all_checks.append("📋 总结")
    all_checks.append("=" * 50)

    # 统计
    api_ok = all(
        os.getenv(var, "").strip()
        for var in ["OPENAI_API_KEY", "AMAP_API_KEY", "JUHE_FLIGHT_KEY", "JUHE_TRAIN_KEY", "QWEATHER_API_KEY"]
    )
    core_ok = bool(os.getenv("OPENAI_API_KEY", "").strip())
    full_data_ok = api_ok

    if not core_ok:
        all_checks.append("   ❌ DeepSeek API Key 未配置 — 系统无法启动")
    elif full_data_ok:
        all_checks.append("   ✅ 全部 4 个实时数据源 Key 已配置 — 零降级运行！")
    else:
        all_checks.append("   ⚠️  DeepSeek Key 已配置，但部分国内 API Key 缺失")
        all_checks.append("      系统可运行，但对应能力将降级到搜索模式")

    # 知识库状态
    try:
        from backend.tools.local_rag import get_chroma_client, get_collection_name
        client = get_chroma_client()
        collection = client.get_or_create_collection(name=get_collection_name())
        count = collection.count()
        if count > 0:
            all_checks.append(f"   ✅ Chroma 知识库就绪: {count} 条")
        else:
            all_checks.append("   ⚠️  Chroma 知识库为空，请运行 ingest 脚本")
    except Exception:
        all_checks.append("   ⚠️  Chroma 知识库未初始化")

    print("\n".join(all_checks))
    print()


if __name__ == "__main__":
    main()
