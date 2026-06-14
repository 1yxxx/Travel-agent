#!/usr/bin/env python3
"""
将 SimpleExample-knowledge-rag/ 目录下的 Markdown 知识文件导入 Chroma 向量数据库。

支持两种模式：
- 本地模式（默认）：存储在 chroma_data/ 目录，无需 API Key
- Chroma Cloud（可选）：需要 CHROMA_API_KEY/TENANT/DATABASE

用法:
  # 本地模式（默认）
  python backend/scripts/ingest_local_knowledge_to_chroma.py

  # Chroma Cloud 模式
  python backend/scripts/ingest_local_knowledge_to_chroma.py \\
    --api-key <CHROMA_API_KEY> --tenant <TENANT> --database <DB>

  # 重建知识库
  python backend/scripts/ingest_local_knowledge_to_chroma.py --recreate
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import chromadb
from chromadb.config import Settings as ChromaSettings


CITY_ALIASES = {
    "beijing": "beijing",
    "北京": "beijing",
    "shanghai": "shanghai",
    "上海": "shanghai",
    "guangzhou": "guangzhou",
    "广州": "guangzhou",
    "shenzhen": "shenzhen",
    "深圳": "shenzhen",
    "hangzhou": "hangzhou",
    "杭州": "hangzhou",
}


def normalize_city(city: str) -> str:
    key = (city or "").strip()
    if not key:
        return ""
    return CITY_ALIASES.get(key.lower(), CITY_ALIASES.get(key, key.lower()))


def split_markdown_text(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    clean = text.replace("\r\n", "\n").strip()
    if not clean:
        return []

    chunks: List[str] = []
    start = 0
    total = len(clean)
    min_break_pos = int(chunk_size * 0.6)

    while start < total:
        end = min(start + chunk_size, total)
        if end < total:
            window = clean[start:end]
            break_pos = max(
                window.rfind("\n\n"),
                window.rfind("\n"),
                window.rfind("。"),
                window.rfind("！"),
                window.rfind("？"),
                window.rfind(". "),
            )
            if break_pos >= min_break_pos:
                end = start + break_pos + 1

        if end <= start:
            end = min(start + chunk_size, total)

        chunk = clean[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= total:
            break

        start = max(start + 1, end - chunk_overlap)

    return chunks


def build_documents(
    knowledge_dir: Path,
    chunk_size: int,
    chunk_overlap: int,
) -> Tuple[List[str], List[str], List[Dict[str, Any]], List[str]]:
    ids: List[str] = []
    docs: List[str] = []
    metas: List[Dict[str, Any]] = []
    source_files: List[str] = []
    ingest_time = datetime.now(timezone.utc).isoformat()

    md_files = sorted(knowledge_dir.glob("*.md"))
    if not md_files:
        raise FileNotFoundError(f"No markdown files found in: {knowledge_dir}")

    for md_file in md_files:
        source_file = md_file.name
        city = normalize_city(md_file.stem)
        source_files.append(source_file)
        text = md_file.read_text(encoding="utf-8")
        chunks = split_markdown_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

        for idx, chunk in enumerate(chunks):
            raw_id = f"{source_file}:{idx}:{chunk}"
            digest = hashlib.sha1(raw_id.encode("utf-8")).hexdigest()[:16]
            doc_id = f"{city}_{idx}_{digest}"

            ids.append(doc_id)
            docs.append(chunk)
            metas.append(
                {
                    "city": city,
                    "source_file": source_file,
                    "chunk_index": idx,
                    "chunk_length": len(chunk),
                    "ingested_at": ingest_time,
                }
            )

    return ids, docs, metas, sorted(set(source_files))


def _is_cloud_mode() -> bool:
    """检查是否配置了 Chroma Cloud 模式。"""
    return bool(
        os.getenv("CHROMA_API_KEY", "").strip()
        and os.getenv("CHROMA_TENANT", "").strip()
        and os.getenv("CHROMA_DATABASE", "").strip()
    )


def _get_local_client(persist_dir: str) -> chromadb.api.ClientAPI:
    """获取本地 ChromaDB PersistentClient。"""
    path = Path(persist_dir).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(path),
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def _get_cloud_client() -> chromadb.api.ClientAPI:
    """获取 Chroma Cloud 客户端。"""
    api_key = os.getenv("CHROMA_API_KEY", "").strip()
    tenant = os.getenv("CHROMA_TENANT", "").strip()
    database = os.getenv("CHROMA_DATABASE", "").strip()
    return chromadb.CloudClient(api_key=api_key, tenant=tenant, database=database)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="将 Markdown 知识文件导入 Chroma 向量数据库（默认本地模式）。"
    )
    parser.add_argument(
        "--knowledge-dir",
        default=str(
            Path(__file__).resolve().parents[2] / "SimpleExample-knowledge-rag"
        ),
        help="Markdown 城市知识文件目录。",
    )
    parser.add_argument(
        "--persist-dir",
        default=os.getenv("CHROMA_PERSIST_DIR", "./chroma_data"),
        help="本地 ChromaDB 数据存储目录（默认 ./chroma_data）。",
    )
    parser.add_argument(
        "--collection",
        default=os.getenv("CHROMA_COLLECTION", "travel_local_expert_knowledge"),
        help="Chroma Collection 名称。",
    )
    parser.add_argument("--chunk-size", type=int, default=900, help="分块大小（字符数）。")
    parser.add_argument("--chunk-overlap", type=int, default=120, help="分块重叠（字符数）。")
    parser.add_argument("--batch-size", type=int, default=64, help="批量上传大小。")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="删除并重建目标 Collection。",
    )
    args = parser.parse_args()

    # 解析知识文件目录
    knowledge_dir = Path(args.knowledge_dir).resolve()
    if not knowledge_dir.exists():
        raise FileNotFoundError(f"知识文件目录不存在: {knowledge_dir}")

    # 分块
    ids, docs, metas, source_files = build_documents(
        knowledge_dir=knowledge_dir,
        chunk_size=max(200, args.chunk_size),
        chunk_overlap=max(0, args.chunk_overlap),
    )
    print(f"已准备 {len(docs)} 个分块 (来自 {len(source_files)} 个文件)")

    # 选择 Chroma 客户端
    if _is_cloud_mode():
        print("→ 使用 Chroma Cloud 模式")
        client = _get_cloud_client()
    else:
        persist_path = str(Path(args.persist_dir).resolve())
        print(f"→ 使用本地 ChromaDB 模式 (数据目录: {persist_path})")
        client = _get_local_client(persist_path)

    collection_name = args.collection.strip()

    # 可选：重建 Collection
    if args.recreate:
        try:
            client.delete_collection(collection_name)
            print(f"已删除旧 Collection: {collection_name}")
        except Exception:
            pass

    collection = client.get_or_create_collection(name=collection_name)

    # 清理旧数据（按 source_file 去重）
    for source_file in source_files:
        try:
            collection.delete(where={"source_file": source_file})
        except Exception:
            pass

    # 批量插入
    batch_size = max(1, args.batch_size)
    for i in range(0, len(ids), batch_size):
        end = i + batch_size
        collection.add(
            ids=ids[i:end],
            documents=docs[i:end],
            metadatas=metas[i:end],
        )
        print(f"已上传分块: {i} → {min(end, len(ids))}")

    total_count = collection.count()
    print(f"✅ 完成！Collection '{collection_name}' 现有 {total_count} 条记录。")


if __name__ == "__main__":
    main()
