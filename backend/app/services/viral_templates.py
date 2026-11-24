from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Iterable

from ..schemas import ProductDNA, SearchQueries


@dataclass(frozen=True)
class CreativeStyleSpec:
    id: str
    label: str
    hints: tuple[str, ...]
    tiktok: tuple[str, ...]
    instagram: tuple[str, ...]
    youtube: tuple[str, ...]


# Battle-tested, 100% product-agnostic viral visual template queries per platform.
# Instagram queries are intentionally concise so both search_reels and no-space hashtag fallback hit huge pools.
CREATIVE_STYLE_BANK: dict[str, CreativeStyleSpec] = {
    "fooh_cgi": CreativeStyleSpec(
        id="fooh_cgi",
        label="FOOH 户外巨物 CGI",
        hints=("fooh", "巨物", "户外", "街头", "地标", "giant", "fake out of home", "cgi"),
        tiktok=("fooh cgi", "giant cgi ad", "fake out of home", "cgi advertising"),
        instagram=("fooh", "cgiadvertising", "fakeoutofhome", "fooh cgi"),
        youtube=("fooh cgi commercial", "giant cgi ad shorts", "fake out of home cgi"),
    ),
    "3d_popout": CreativeStyleSpec(
        id="3d_popout",
        label="3D 悬浮 / 画册弹出",
        hints=("3d", "悬浮", "画册", "杂志", "弹出", "pop out", "floating", "levitat", "变形", "book"),
        tiktok=("3d product animation", "cgi product reveal", "3d floating ad", "surreal product ad"),
        instagram=("3dproductanimation", "cgiad", "3dcommercial", "3d product reveal"),
        youtube=("3d product animation commercial", "cgi product reveal shorts", "satisfying 3d commercial"),
    ),
    "ai_commercial": CreativeStyleSpec(
        id="ai_commercial",
        label="AI 超现实大片",
        hints=("ai", "可灵", "kling", "sora", "runway", "veo", "超现实", "surreal", "ai广告"),
        tiktok=("ai commercial ad", "kling ai commercial", "ai product commercial", "viral ai ad"),
        instagram=("aicommercial", "aiadvertising", "aiproductvideo", "ai commercial"),
        youtube=("ai commercial video shorts", "ai product commercial", "kling ai commercial shorts"),
    ),
    "vfx_transition": CreativeStyleSpec(
        id="vfx_transition",
        label="无缝转场 / 脑洞运镜",
        hints=("转场", "运镜", "vfx", "特效", "脑洞", "transition", "match cut", "创意拍摄", "大片"),
        tiktok=("creative commercial transition", "vfx product ad", "mind blowing commercial", "creative product shoot"),
        instagram=("creativecommercial", "commercialtransitions", "vfxcommercial", "productvideography"),
        youtube=("creative commercial behind the scenes", "viral commercial transition shorts", "creative product video shorts"),
    ),
    "miniature_world": CreativeStyleSpec(
        id="miniature_world",
        label="微缩世界 / 定格动画",
        hints=("微缩", "小人国", "定格", "miniature", "tiny", "stop motion", "微观", "积木"),
        tiktok=("miniature product ad", "tiny workers cgi", "stop motion commercial", "miniature commercial"),
        instagram=("miniaturecommercial", "stopmotionad", "tinyworld", "miniature ad"),
        youtube=("miniature product commercial", "tiny workers ai commercial", "stop motion product ad"),
    ),
    "luxury_aesthetic": CreativeStyleSpec(
        id="luxury_aesthetic",
        label="极简高级美学大片",
        hints=("极简", "高级", "美学", "奢华", "luxury", "minimalist", "aesthetic", "质感", "电影感"),
        tiktok=("luxury commercial ad", "viral ad concept", "creative brand ad", "aesthetic commercial"),
        instagram=("luxurycommercial", "creativeadvertising", "brandcommercial", "commercialfilm"),
        youtube=("best creative commercial shorts", "luxury product commercial", "viral ad idea shorts"),
    ),
}

DEFAULT_STYLE_ORDER: tuple[str, ...] = (
    "fooh_cgi",
    "3d_popout",
    "vfx_transition",
    "ai_commercial",
    "miniature_world",
    "luxury_aesthetic",
)

# Bilingual category synonym expansion for strict product-leak prevention in cross_category mode.
_CATEGORY_SYNONYM_GROUPS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("灯", "照明", "灯具", "灯带", "台灯", "吊灯", "筒灯", "射灯", "吸顶灯", "led", "light", "lighting", "lamp", "bulb", "luminaire", "fixture", "chandelier", "neon"),
        ("led", "light", "lights", "lighting", "lamp", "lamps", "bulb", "bulbs", "strip", "strips", "fixture", "fixtures", "luminaire", "chandelier", "neon", "lantern", "glow", "illumination", "linear", "batten", "sconce", "spotlight", "downlight", "灯", "照明", "灯具", "灯带"),
    ),
    (
        ("风扇", "吹风", "空调", "制冷", "降温", "fan", "cooler", "cooling", "aircon"),
        ("fan", "fans", "cooler", "cooling", "breeze", "airflow", "aircon", "blower", "风扇", "制冷", "降温"),
    ),
    (
        ("护肤", "精华", "面霜", "乳液", "面膜", "防晒", "洁面", "美妆", "化妆品", "skincare", "serum", "cream", "lotion", "cosmetic"),
        ("skincare", "serum", "cream", "lotion", "cleanser", "moisturizer", "sunscreen", "cosmetic", "cosmetics", "makeup", "lipstick", "护肤", "精华", "面霜", "美妆"),
    ),
    (
        ("香水", "香氛", "香薰", "perfume", "fragrance", "cologne", "scent", "diffuser"),
        ("perfume", "fragrance", "cologne", "scent", "aroma", "diffuser", "candle", "香水", "香氛", "香薰"),
    ),
    (
        ("杯", "水杯", "保温杯", "咖啡杯", "壶", "tumbler", "mug", "cup", "bottle", "flask", "thermos"),
        ("tumbler", "mug", "cup", "bottle", "flask", "thermos", "drinkware", "kettle", "水杯", "保温杯", "咖啡杯"),
    ),
    (
        ("沙发", "桌", "椅", "床", "柜", "家具", "家居", "sofa", "chair", "table", "desk", "furniture", "cabinet", "bed"),
        ("sofa", "couch", "chair", "table", "desk", "furniture", "cabinet", "shelf", "bed", "mattress", "沙发", "桌椅", "家具"),
    ),
    (
        ("鞋", "球鞋", "运动鞋", "靴", "拖鞋", "shoe", "sneaker", "boot", "sandal", "footwear"),
        ("shoe", "shoes", "sneaker", "sneakers", "boot", "boots", "sandal", "footwear", "heel", "鞋", "球鞋", "运动鞋"),
    ),
    (
        ("包", "手袋", "背包", "行李箱", "钱包", "bag", "handbag", "backpack", "purse", "tote", "luggage", "wallet"),
        ("bag", "bags", "handbag", "backpack", "purse", "tote", "luggage", "suitcase", "wallet", "包", "手袋", "背包"),
    ),
    (
        ("耳机", "音箱", "音响", "麦", "headphone", "earbud", "airpod", "speaker", "audio", "mic"),
        ("headphone", "headphones", "earbud", "earbuds", "earphone", "speaker", "speakers", "audio", "headset", "耳机", "音箱", "音响"),
    ),
    (
        ("手表", "腕表", "表", "watch", "smartwatch", "timepiece"),
        ("watch", "watches", "smartwatch", "timepiece", "wristwatch", "手表", "腕表"),
    ),
    (
        ("服装", "衣服", "外套", "卫衣", "T恤", "裙", "裤", "apparel", "clothing", "jacket", "hoodie", "shirt", "dress", "pants"),
        ("apparel", "clothing", "jacket", "hoodie", "shirt", "tshirt", "dress", "pants", "jeans", "fashion", "服装", "衣服", "外套"),
    ),
    (
        ("厨具", "锅", "刀", "咖啡机", "空气炸锅", "小家电", "kitchen", "cookware", "pan", "blender", "airfryer"),
        ("kitchen", "kitchenware", "cookware", "pan", "pot", "knife", "blender", "airfryer", "espresso", "厨具", "小家电"),
    ),
    (
        ("手机壳", "充电宝", "数据线", "支架", "键盘", "鼠标", "charger", "powerbank", "keyboard", "mouse", "phonecase"),
        ("phonecase", "charger", "powerbank", "cable", "keyboard", "mouse", "stand", "手机壳", "充电宝", "键盘", "鼠标"),
    ),
    (
        ("宠物", "猫", "狗", "pet", "cat", "dog"),
        ("pet", "pets", "cat", "cats", "dog", "dogs", "collar", "litter", "宠物", "猫", "狗"),
    ),
)

# Generic words that belong in viral creative queries and must NEVER be treated as forbidden product terms.
_SAFE_CREATIVE_WORDS: set[str] = {
    "ad",
    "ads",
    "ai",
    "3d",
    "cgi",
    "fooh",
    "vfx",
    "viral",
    "creative",
    "commercial",
    "product",
    "products",
    "brand",
    "video",
    "shorts",
    "reel",
    "reels",
    "animation",
    "reveal",
    "transition",
    "transitions",
    "advertising",
    "concept",
    "idea",
    "shoot",
    "film",
    "luxury",
    "aesthetic",
    "surreal",
    "miniature",
    "tiny",
    "workers",
    "stop",
    "motion",
    "floating",
    "giant",
    "fake",
    "out",
    "of",
    "home",
    "mind",
    "blowing",
    "best",
    "behind",
    "the",
    "scenes",
    "satisfying",
    "kling",
    "design",
    "showcase",
    "world",
    "商业",
    "广告",
    "产品",
    "爆款",
    "创意",
    "视频",
    "模板",
    "通用",
    "消费品",
    "好物",
}


def normalize_creative_styles(raw_styles: Iterable[str] | None) -> list[str]:
    if not raw_styles:
        return []
    out: list[str] = []
    for item in raw_styles:
        key = str(item).strip().lower()
        if key in CREATIVE_STYLE_BANK and key not in out:
            out.append(key)
    return out


def infer_styles_from_instruction(user_instruction: str) -> list[str]:
    text = (user_instruction or "").strip().lower()
    if not text:
        return []
    matched: list[str] = []
    for style_id in DEFAULT_STYLE_ORDER:
        spec = CREATIVE_STYLE_BANK[style_id]
        if any(h in text for h in spec.hints):
            matched.append(style_id)
    return matched


def _tokenize_terms(text: str) -> set[str]:
    tokens: set[str] = set()
    lower = (text or "").lower()
    for word in re.findall(r"[a-z0-9]{2,}", lower):
        if word not in _SAFE_CREATIVE_WORDS:
            tokens.add(word)
    for zh in re.findall(r"[\u4e00-\u9fff]{1,6}", lower):
        if zh not in _SAFE_CREATIVE_WORDS and len(zh) >= 2:
            tokens.add(zh)
    return tokens


def extract_forbidden_product_terms(
    product_dna: ProductDNA,
    extra_texts: Iterable[str] = (),
) -> set[str]:
    """Build a strict set of product-category words that MUST NOT leak into cross-category queries."""
    source_chunks = [
        product_dna.product_name,
        product_dna.category,
        *product_dna.category_leak_keywords,
        *extra_texts,
    ]
    combined_lower = " ".join(c for c in source_chunks if c).lower()
    forbidden: set[str] = set()

    for chunk in source_chunks:
        forbidden.update(_tokenize_terms(chunk))

    # Also add single-char strong Chinese product category triggers when expanded via synonym groups
    for triggers, expanded in _CATEGORY_SYNONYM_GROUPS:
        if any(t in combined_lower for t in triggers):
            forbidden.update(expanded)

    forbidden.difference_update(_SAFE_CREATIVE_WORDS)
    return forbidden


def contains_product_leak(query: str, forbidden_terms: set[str]) -> bool:
    if not query.strip() or not forbidden_terms:
        return False
    lower = query.lower()
    words = set(re.findall(r"[a-z0-9]+", lower))
    compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", lower)
    for term in forbidden_terms:
        if not term:
            continue
        if re.fullmatch(r"[a-z0-9]+", term):
            if term in words:
                return True
            if len(term) >= 4 and term in compact:
                return True
        else:
            if term in lower:
                return True
    return False


def item_matches_same_category(
    original_featured_item: str,
    product_dna: ProductDNA,
) -> bool:
    """Secondary deterministic safeguard: detect when Stage 3's original_featured_item
    is obviously the exact same category as the user's product."""
    item_text = (original_featured_item or "").strip().lower()
    if not item_text or item_text in ("无明确实物", "未知", "通用产品"):
        return False
    forbidden = extract_forbidden_product_terms(product_dna)
    # Remove photography/lighting-ambiguous words from item matching unless strong lamp terms match
    ambiguous = {"linear", "glow", "modern", "minimal", "industrial", "commercial", "portable", "mini", "smart", "wireless"}
    strict_terms = forbidden - ambiguous
    return contains_product_leak(item_text, strict_terms)


def _pick_cross_category_queries_for_platform(
    platform: str,
    *,
    count: int,
    preferred_styles: list[str],
    forbidden_terms: set[str],
    rng: random.Random,
) -> list[str]:
    if preferred_styles:
        style_order = list(preferred_styles)
        remaining = [s for s in DEFAULT_STYLE_ORDER if s not in style_order]
        rng.shuffle(remaining)
        style_order.extend(remaining)
    else:
        style_order = list(DEFAULT_STYLE_ORDER)
        rng.shuffle(style_order)

    picked: list[str] = []
    seen: set[str] = set()

    # Pass 1: pick 1 diverse query from distinct archetypes first
    for style_id in style_order:
        if len(picked) >= count:
            break
        spec = CREATIVE_STYLE_BANK[style_id]
        pool = list(getattr(spec, platform, spec.tiktok))
        rng.shuffle(pool)
        for q in pool:
            q_norm = q.strip().lower()
            if not q_norm or q_norm in seen:
                continue
            if contains_product_leak(q, forbidden_terms):
                continue
            picked.append(q.strip())
            seen.add(q_norm)
            break

    # Pass 2: if preferred_styles has 1-2 styles and count > len(preferred_styles),
    # allow filling from preferred styles' additional queries first before fallback
    if len(picked) < count:
        for style_id in style_order:
            spec = CREATIVE_STYLE_BANK[style_id]
            for q in getattr(spec, platform, spec.tiktok):
                if len(picked) >= count:
                    break
                q_norm = q.strip().lower()
                if not q_norm or q_norm in seen:
                    continue
                if contains_product_leak(q, forbidden_terms):
                    continue
                picked.append(q.strip())
                seen.add(q_norm)
            if len(picked) >= count:
                break

    # Absolute fallback (never uses product category)
    if len(picked) < count:
        for fallback_q in ("fooh cgi", "3d product animation", "creative commercial"):
            if len(picked) >= count:
                break
            if fallback_q not in seen:
                picked.append(fallback_q)
                seen.add(fallback_q)

    return picked[:count]


def resolve_platform_queries(
    *,
    product_dna: ProductDNA,
    search_strategy: str = "cross_category",
    creative_styles: Iterable[str] | None = None,
    user_instruction: str = "",
    seed: int | None = None,
) -> SearchQueries:
    """Deterministically build final search queries per platform according to search_strategy.

    - cross_category: 100% decoupled from the uploaded product! Never uses LLM product-derived
      queries; pulls strictly from curated cross-category viral template archetypes and enforces
      a zero-product-leak guardrail.
    - hybrid: 2 strictly cross-category viral template queries + 1 LLM C-end category query.
    - same_category: Uses LLM C-end category queries directly.
    """
    rng = random.Random(seed)
    forbidden = extract_forbidden_product_terms(product_dna)
    explicit_styles = normalize_creative_styles(creative_styles)
    inferred_styles = infer_styles_from_instruction(user_instruction)
    preferred_styles = explicit_styles or inferred_styles

    out: dict[str, list[str]] = {}
    llm_map = {
        "tiktok": list(product_dna.search_queries.tiktok or []),
        "instagram": list(product_dna.search_queries.instagram or []),
        "youtube": list(product_dna.search_queries.youtube or []),
    }

    for plat in ("tiktok", "instagram", "youtube"):
        if search_strategy == "same_category":
            raw = [q.strip() for q in llm_map[plat] if q and q.strip()]
            if not raw:
                raw = [f"{product_dna.product_name} viral", f"{product_dna.category} trending"]
            out[plat] = raw[:3]
        elif search_strategy == "hybrid":
            cross_qs = _pick_cross_category_queries_for_platform(
                plat,
                count=2,
                preferred_styles=preferred_styles,
                forbidden_terms=forbidden,
                rng=rng,
            )
            seen = {q.lower() for q in cross_qs}
            cat_q = next(
                (q.strip() for q in llm_map[plat] if q and q.strip() and q.strip().lower() not in seen),
                None,
            )
            if cat_q:
                out[plat] = [*cross_qs, cat_q][:3]
            else:
                out[plat] = _pick_cross_category_queries_for_platform(
                    plat,
                    count=3,
                    preferred_styles=preferred_styles,
                    forbidden_terms=forbidden,
                    rng=rng,
                )
        else:
            # Strict cross_category mode: 100% decoupled from the uploaded product!
            # If user explicitly picked 1-2 creative styles, prioritize 2-3 queries from those styles.
            if explicit_styles and len(explicit_styles) <= 2:
                picked: list[str] = []
                seen_q: set[str] = set()
                for st_id in explicit_styles:
                    pool = list(getattr(CREATIVE_STYLE_BANK[st_id], plat))
                    rng.shuffle(pool)
                    quota = 3 if len(explicit_styles) == 1 else 2
                    added_here = 0
                    for q in pool:
                        if len(picked) >= 3 or added_here >= quota:
                            break
                        qn = q.strip().lower()
                        if qn not in seen_q and not contains_product_leak(q, forbidden):
                            picked.append(q.strip())
                            seen_q.add(qn)
                            added_here += 1
                if len(picked) < 3:
                    extra = _pick_cross_category_queries_for_platform(
                        plat,
                        count=3,
                        preferred_styles=explicit_styles,
                        forbidden_terms=forbidden,
                        rng=rng,
                    )
                    for q in extra:
                        if len(picked) >= 3:
                            break
                        if q.lower() not in seen_q:
                            picked.append(q)
                            seen_q.add(q.lower())
                out[plat] = picked[:3]
            else:
                out[plat] = _pick_cross_category_queries_for_platform(
                    plat,
                    count=3,
                    preferred_styles=preferred_styles,
                    forbidden_terms=forbidden,
                    rng=rng,
                )

    return SearchQueries(
        tiktok=out["tiktok"],
        instagram=out["instagram"],
        youtube=out["youtube"],
    )
