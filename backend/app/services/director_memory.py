from __future__ import annotations

import re
from typing import Iterable

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..models import DirectorMemory
from ..schemas import LearnedMemoryItem

CATEGORY_LABELS: dict[str, str] = {
    "character": "人物形象偏好",
    "scene_style": "场景与调性偏好",
    "product_replacement": "产品替换手法",
    "pacing_framing": "画面框架与改写纪律",
    "taboo": "禁区与避坑规则",
}

VALID_CATEGORIES = set(CATEGORY_LABELS.keys())


def _bigrams(text: str) -> set[str]:
    clean = re.sub(r"\s+", "", (text or "").lower())
    clean = re.sub(r"[^\w\u4e00-\u9fff]+", "", clean)
    if len(clean) < 2:
        return {clean} if clean else set()
    return {clean[i : i + 2] for i in range(len(clean) - 1)}


def _similarity(a: str, b: str) -> float:
    ba = _bigrams(a)
    bb = _bigrams(b)
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / max(len(ba | bb), 1)


def _scope_matches(scope: str, product_name: str, category: str) -> bool:
    s = (scope or "global").strip().lower()
    if not s or s in ("global", "通用", "全部", "all"):
        return True
    target = f"{product_name or ''} {category or ''}".lower()
    if not target.strip():
        return False
    tokens = [t for t in re.split(r"[/,，、\s]+", s) if len(t) >= 2]
    return any(t in target for t in tokens)


def load_active_memories(
    db: Session,
    *,
    product_name: str = "",
    category: str = "",
    limit: int = 16,
) -> list[DirectorMemory]:
    rows = list(
        db.scalars(
            select(DirectorMemory)
            .where(DirectorMemory.is_active == True)  # noqa: E712
            .order_by(desc(DirectorMemory.confidence_hits), desc(DirectorMemory.updated_at))
            .limit(60)
        ).all()
    )
    if not rows:
        return []

    scoped: list[tuple[int, int, DirectorMemory]] = []
    for row in rows:
        s = (row.product_scope or "global").strip().lower()
        is_global = s in ("", "global", "通用", "全部", "all")
        if is_global:
            priority = 1
        elif _scope_matches(row.product_scope, product_name, category):
            priority = 2
        else:
            continue
        scoped.append((priority, row.confidence_hits or 1, row))

    scoped.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scoped[:limit]]


def load_director_memory_block(
    db: Session,
    *,
    product_name: str = "",
    category: str = "",
    limit: int = 16,
) -> str:
    """Format active long-term memories into a structured prompt section for the AI Director."""
    memories = load_active_memories(
        db, product_name=product_name, category=category, limit=limit
    )
    if not memories:
        return ""

    lines = [
        "【你的专属长期导演记忆库（来自用户历史多轮共创沉淀 — 必须优先吸收并自然运用到本次拆解与建议中！）】"
    ]
    for idx, mem in enumerate(memories, start=1):
        cat_label = CATEGORY_LABELS.get(mem.category, "导演偏好")
        scope_label = (
            "通用"
            if (mem.product_scope or "global").lower() in ("", "global", "通用")
            else f"适用:{mem.product_scope}"
        )
        hits = f"（已强化 {mem.confidence_hits} 次）" if (mem.confidence_hits or 1) > 1 else ""
        ex = f"｜参考案例：{mem.example_snippet}" if mem.example_snippet else ""
        lines.append(
            f"{idx}. [{cat_label} · {scope_label}]{hits} {mem.rule_summary}{ex}"
        )
    return "\n".join(lines)


def save_learned_memories(
    db: Session,
    items: Iterable[LearnedMemoryItem],
    *,
    source_video_title: str = "",
) -> list[DirectorMemory]:
    """Persist newly distilled creative rules with fuzzy deduplication & confidence reinforcement."""
    existing = list(
        db.scalars(
            select(DirectorMemory).order_by(desc(DirectorMemory.updated_at)).limit(100)
        ).all()
    )
    touched: list[DirectorMemory] = []

    for item in items:
        summary = (item.rule_summary or "").strip()
        if len(summary) < 6:
            continue
        cat = item.category if item.category in VALID_CATEGORIES else "product_replacement"
        scope = (item.product_scope or "global").strip()[:80] or "global"
        example = (item.example_snippet or "").strip()[:300]

        matched: DirectorMemory | None = None
        for row in existing:
            if row.category == cat and _similarity(row.rule_summary, summary) >= 0.58:
                matched = row
                break
            if _similarity(row.rule_summary, summary) >= 0.72:
                matched = row
                break

        if matched is not None:
            matched.confidence_hits = (matched.confidence_hits or 1) + 1
            matched.is_active = True
            if len(summary) > len(matched.rule_summary):
                matched.rule_summary = summary
            if example:
                matched.example_snippet = example
            if source_video_title:
                matched.source_video_title = source_video_title[:200]
            touched.append(matched)
        else:
            row = DirectorMemory(
                category=cat,
                product_scope=scope,
                rule_summary=summary,
                example_snippet=example,
                source_video_title=source_video_title[:200],
                confidence_hits=1,
                is_active=True,
            )
            db.add(row)
            existing.append(row)
            touched.append(row)

    if touched:
        db.commit()
        for row in touched:
            db.refresh(row)
    return touched
