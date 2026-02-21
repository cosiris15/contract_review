"""Local FIDIC skill: semantic retrieval over ER document sections."""

from __future__ import annotations

import logging
import os
from typing import Any, List

import numpy as np
from pydantic import BaseModel, Field

from ..local._utils import ensure_dict

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL = "text-embedding-v3"
_BATCH_SIZE = 25
_MIN_SCORE = 0.3


class SearchErInput(BaseModel):
    clause_id: str
    document_structure: Any
    er_structure: Any = None
    query: str = ""
    top_k: int = 5


class ErSection(BaseModel):
    section_id: str
    text: str
    relevance_score: float


class SearchErOutput(BaseModel):
    clause_id: str
    relevant_sections: List[ErSection] = Field(default_factory=list)
    total_found: int = 0
    search_method: str = "dashscope_embedding"


def _collect_er_sections(structure: Any) -> list[dict[str, str]]:
    payload = ensure_dict(structure)
    clauses = payload.get("clauses", [])
    if not isinstance(clauses, list):
        return []

    out: list[dict[str, str]] = []

    def walk(nodes: list[Any]) -> None:
        for node in nodes:
            item = ensure_dict(node)
            if not item:
                continue
            section_id = str(item.get("clause_id", "") or "")
            text = str(item.get("text", "") or "").strip()
            if section_id and text:
                out.append({"section_id": section_id, "text": text})
            children = item.get("children", [])
            if isinstance(children, list) and children:
                walk(children)

    walk(clauses)
    return out


def _embed_texts(texts: list[str]) -> np.ndarray:
    """Embed text list with Dashscope. Return empty array on any failure."""
    if not texts:
        return np.array([])

    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        logger.warning("DASHSCOPE_API_KEY 未配置，跳过 ER embedding 检索")
        return np.array([])

    try:
        import dashscope
        from dashscope import TextEmbedding
    except Exception as exc:  # pragma: no cover - dependency guard
        logger.warning("Dashscope SDK 不可用: %s", exc)
        return np.array([])

    dashscope.api_key = api_key
    embeddings: list[list[float]] = []
    for idx in range(0, len(texts), _BATCH_SIZE):
        batch = texts[idx : idx + _BATCH_SIZE]
        try:
            response = TextEmbedding.call(model=_EMBEDDING_MODEL, input=batch)
        except Exception as exc:
            logger.warning("Dashscope Embedding 异常: %s", exc)
            return np.array([])

        if getattr(response, "status_code", None) != 200:
            logger.warning("Dashscope Embedding 调用失败: %s", getattr(response, "message", "unknown"))
            return np.array([])

        data = getattr(response, "output", {}) or {}
        items = data.get("embeddings", [])
        if not isinstance(items, list) or len(items) != len(batch):
            logger.warning("Dashscope Embedding 返回格式异常")
            return np.array([])
        for item in items:
            if not isinstance(item, dict) or "embedding" not in item:
                logger.warning("Dashscope Embedding item 缺少 embedding")
                return np.array([])
            embeddings.append(item["embedding"])

    return np.array(embeddings)


def _cosine_similarity(query_vec: np.ndarray, doc_vecs: np.ndarray) -> np.ndarray:
    if query_vec.size == 0 or doc_vecs.size == 0:
        return np.array([])
    dot_products = np.dot(doc_vecs, query_vec)
    query_norm = np.linalg.norm(query_vec)
    doc_norms = np.linalg.norm(doc_vecs, axis=1)
    norms = query_norm * doc_norms
    norms[norms == 0] = 1.0
    return dot_products / norms


async def search_er(input_data: SearchErInput) -> SearchErOutput:
    query = (input_data.query or "").strip()
    if not query:
        query = input_data.clause_id

    sections = _collect_er_sections(input_data.er_structure)
    if not sections:
        return SearchErOutput(clause_id=input_data.clause_id)

    texts = [query] + [row["text"] for row in sections]
    vectors = _embed_texts(texts)
    if vectors.size == 0 or len(vectors) != len(texts):
        return SearchErOutput(clause_id=input_data.clause_id)

    scores = _cosine_similarity(vectors[0], vectors[1:])
    if scores.size == 0:
        return SearchErOutput(clause_id=input_data.clause_id)

    ranked: list[tuple[float, dict[str, str]]] = [
        (float(score), section) for score, section in zip(scores.tolist(), sections)
    ]
    ranked.sort(key=lambda x: x[0], reverse=True)

    top_k = max(1, int(input_data.top_k or 5))
    results: list[ErSection] = []
    for score, section in ranked:
        if score < _MIN_SCORE:
            continue
        results.append(
            ErSection(
                section_id=section["section_id"],
                text=section["text"],
                relevance_score=round(score, 4),
            )
        )
        if len(results) >= top_k:
            break

    return SearchErOutput(
        clause_id=input_data.clause_id,
        relevant_sections=results,
        total_found=len(results),
    )
