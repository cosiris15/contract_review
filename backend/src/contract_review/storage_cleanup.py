"""
Supabase Storage 清理任务

按保留天数删除 documents bucket 中的旧文件。
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .supabase_client import get_storage_bucket, get_supabase_client

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 3
ENV_RETENTION_DAYS = "CONTRACT_FILE_RETENTION_DAYS"


def get_retention_days() -> int:
    raw = os.getenv(ENV_RETENTION_DAYS, str(DEFAULT_RETENTION_DAYS))
    try:
        days = int(raw)
    except ValueError:
        logger.warning(f"无效的 {ENV_RETENTION_DAYS}={raw}，使用默认值 {DEFAULT_RETENTION_DAYS}")
        return DEFAULT_RETENTION_DAYS
    return max(days, 1)


def _fetch_old_objects(bucket: str, cutoff: datetime) -> List[Dict[str, Any]]:
    client = get_supabase_client()
    objects: List[Dict[str, Any]] = []
    batch_size = 1000
    start = 0
    cutoff_iso = cutoff.isoformat()

    while True:
        response = (
            client.table("storage.objects")
            .select("name,created_at")
            .eq("bucket_id", bucket)
            .lt("created_at", cutoff_iso)
            .range(start, start + batch_size - 1)
            .execute()
        )
        data = response.data or []
        if not data:
            break
        objects.extend(data)
        if len(data) < batch_size:
            break
        start += batch_size

    return objects


def _delete_objects(bucket: str, paths: List[str]) -> Dict[str, Any]:
    client = get_supabase_client()
    deleted = 0
    failed = 0
    errors: List[str] = []
    chunk_size = 100

    for i in range(0, len(paths), chunk_size):
        chunk = paths[i:i + chunk_size]
        try:
            client.storage.from_(bucket).remove(chunk)
            deleted += len(chunk)
        except Exception as exc:
            failed += len(chunk)
            errors.append(str(exc))
            logger.error(f"删除 Storage 文件失败: {exc}")

    return {"deleted": deleted, "failed": failed, "errors": errors}


def cleanup_old_files(days: Optional[int] = None) -> Dict[str, Any]:
    retention_days = days or get_retention_days()
    bucket = get_storage_bucket()
    cutoff = datetime.utcnow() - timedelta(days=retention_days)

    logger.info(f"开始清理 Storage: bucket={bucket}, retention_days={retention_days}")

    result: Dict[str, Any] = {
        "retention_days": retention_days,
        "files_deleted": 0,
        "files_failed": 0,
        "errors": [],
        "started_at": datetime.utcnow().isoformat(),
        "completed_at": None,
    }

    try:
        objects = _fetch_old_objects(bucket, cutoff)
        paths = [obj["name"] for obj in objects if obj.get("name")]
        if not paths:
            result["completed_at"] = datetime.utcnow().isoformat()
            return result

        delete_result = _delete_objects(bucket, paths)
        result["files_deleted"] = delete_result["deleted"]
        result["files_failed"] = delete_result["failed"]
        result["errors"] = delete_result["errors"]
        result["completed_at"] = datetime.utcnow().isoformat()
        return result
    except Exception as exc:
        logger.error(f"Storage 清理失败: {exc}")
        result["errors"].append(str(exc))
        result["completed_at"] = datetime.utcnow().isoformat()
        return result


async def cleanup_old_files_async(days: Optional[int] = None) -> Dict[str, Any]:
    return await asyncio.to_thread(cleanup_old_files, days)
