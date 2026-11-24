from __future__ import annotations

from app.schemas import ProductDNA, SearchQueries
from app.services.collectors.base import CandidateVideo
from app.services.pipeline import _ScreenedCandidate, select_candidates_for_deep_analysis
from app.services.viral_templates import (
    CREATIVE_STYLE_BANK,
    contains_product_leak,
    extract_forbidden_product_terms,
    item_matches_same_category,
    resolve_platform_queries,
)


def _led_dna_with_leaky_llm_queries() -> ProductDNA:
    return ProductDNA(
        product_name="LED 线性灯",
        category="商业照明 / 线性灯具",
        physical_form="白色长条线性灯具",
        category_leak_keywords=["led", "lighting", "lamp", "linear light", "灯具"],
        # Simulate an adversarial/leaky LLM that disobeyed the prompt and output same-category queries
        search_queries=SearchQueries(
            tiktok=["led strips", "aesthetic lighting glow up", "linear lamp commercial"],
            instagram=["minimalist lighting", "led light room", "commercial lamp ad"],
            youtube=["led light setup shorts", "linear lighting review", "room lamp glow"],
        ),
    )


def test_cross_category_queries_are_100_percent_decoupled_from_product():
    dna = _led_dna_with_leaky_llm_queries()
    forbidden = extract_forbidden_product_terms(dna)

    assert "led" in forbidden
    assert "light" in forbidden
    assert "lighting" in forbidden
    assert "lamp" in forbidden
    assert "strip" in forbidden

    resolved = resolve_platform_queries(
        product_dna=dna,
        search_strategy="cross_category",
        creative_styles=[],
        user_instruction="",
        seed=42,
    )

    for plat, queries in [
        ("tiktok", resolved.tiktok),
        ("instagram", resolved.instagram),
        ("youtube", resolved.youtube),
    ]:
        assert len(queries) == 3, f"{plat} should have 3 queries"
        for q in queries:
            assert not contains_product_leak(q, forbidden), f"Leaked product term in {plat}: {q}"
            assert "led" not in q.lower()
            assert "light" not in q.lower()
            assert "lamp" not in q.lower()


def test_cross_category_respects_selected_creative_styles_and_instruction_hints():
    dna = _led_dna_with_leaky_llm_queries()

    # Explicit style selection
    fooh_queries = resolve_platform_queries(
        product_dna=dna,
        search_strategy="cross_category",
        creative_styles=["fooh_cgi"],
        seed=7,
    )
    assert set(fooh_queries.tiktok).issubset(set(CREATIVE_STYLE_BANK["fooh_cgi"].tiktok))
    assert set(fooh_queries.instagram).issubset(set(CREATIVE_STYLE_BANK["fooh_cgi"].instagram))
    assert set(fooh_queries.youtube).issubset(set(CREATIVE_STYLE_BANK["fooh_cgi"].youtube))

    # Inferred from Chinese user instruction
    mini_queries = resolve_platform_queries(
        product_dna=dna,
        search_strategy="cross_category",
        creative_styles=[],
        user_instruction="我想找微缩世界和小人国施工风格的高赞广告",
        seed=9,
    )
    assert any(q in CREATIVE_STYLE_BANK["miniature_world"].tiktok for q in mini_queries.tiktok)


def test_hybrid_and_same_category_strategies():
    dna = _led_dna_with_leaky_llm_queries()
    forbidden = extract_forbidden_product_terms(dna)

    hybrid = resolve_platform_queries(
        product_dna=dna,
        search_strategy="hybrid",
        seed=3,
    )
    # First 2 slots per platform are guaranteed cross-category; 3rd slot uses LLM category query
    for q in hybrid.tiktok[:2]:
        assert not contains_product_leak(q, forbidden)
    assert hybrid.tiktok[2] == "led strips"

    same = resolve_platform_queries(
        product_dna=dna,
        search_strategy="same_category",
        seed=3,
    )
    assert same.tiktok == ["led strips", "aesthetic lighting glow up", "linear lamp commercial"]


def test_stage3_selection_strictly_excludes_same_category_and_balances_platforms():
    dna = _led_dna_with_leaky_llm_queries()

    # Confirm studio lighting photography terms do NOT falsely mark perfume as lamp,
    # whereas actual LED lamp item IS detected as same-category.
    assert item_matches_same_category("LED 线性灯条", dna) is True
    assert item_matches_same_category("巨型香水瓶", dna) is False
    assert item_matches_same_category("3D 悬浮真皮沙发", dna) is False

    def _cand(plat: str, vid: str, views: int = 500_000) -> CandidateVideo:
        return CandidateVideo(
            platform=plat,
            platform_video_id=vid,
            video_url=f"https://example.com/{plat}/{vid}",
            title=f"Video {vid}",
            views=views,
            likes=20_000,
        )

    scored = [
        # Same-category LED video with artificially high score (flagged by AI)
        _ScreenedCandidate(
            candidate=_cand("tiktok", "same_led_1", 2_000_000),
            preliminary_score=98,
            visual_creativity_score=95,
            is_same_category=True,
            is_replaceable=True,
            original_featured_item="LED 灯带",
        ),
        # Same-category lamp video that AI FORGOT to flag (caught by deterministic item check!)
        _ScreenedCandidate(
            candidate=_cand("instagram", "same_led_2", 1_500_000),
            preliminary_score=96,
            visual_creativity_score=90,
            is_same_category=False,
            is_replaceable=True,
            original_featured_item="极简线性灯具",
        ),
        # True cross-category viral templates across all 3 platforms
        _ScreenedCandidate(
            candidate=_cand("tiktok", "cross_tk_1", 1_200_000),
            preliminary_score=90,
            visual_creativity_score=96,
            is_same_category=False,
            is_replaceable=True,
            original_featured_item="街头巨型香水瓶 FOOH",
        ),
        _ScreenedCandidate(
            candidate=_cand("tiktok", "cross_tk_2", 1_100_000),
            preliminary_score=89,
            visual_creativity_score=94,
            is_same_category=False,
            is_replaceable=True,
            original_featured_item="画册 3D 悬浮沙发",
        ),
        _ScreenedCandidate(
            candidate=_cand("instagram", "cross_ig_1", 900_000),
            preliminary_score=86,
            visual_creativity_score=92,
            is_same_category=False,
            is_replaceable=True,
            original_featured_item="微缩世界施工手表",
        ),
        _ScreenedCandidate(
            candidate=_cand("youtube", "cross_yt_1", 800_000),
            preliminary_score=85,
            visual_creativity_score=91,
            is_same_category=False,
            is_replaceable=True,
            original_featured_item="脑洞转场运动鞋",
        ),
    ]

    selected, excluded_count = select_candidates_for_deep_analysis(
        scored_candidates=scored,
        product_dna=dna,
        search_strategy="cross_category",
        target_count=3,
    )

    assert excluded_count == 2
    selected_ids = [c.platform_video_id for c, _, _ in selected]
    # Zero same-category videos allowed!
    assert "same_led_1" not in selected_ids
    assert "same_led_2" not in selected_ids
    # Multi-platform diversity: 1 TikTok + 1 Instagram + 1 YouTube!
    selected_platforms = {c.platform for c, _, _ in selected}
    assert selected_platforms == {"tiktok", "instagram", "youtube"}


def test_real_person_and_photorealistic_ai_only_blocks_cartoons_and_animations():
    from app.services.filter_engine import run_hard_filter
    from app.services.viral_templates import is_cartoon_or_animation_text

    # 1. Zero-token keyword detector catches real examples from screenshot + Chinese anime terms
    assert is_cartoon_or_animation_text('Prada Holiday 2026 | "Drawing Prada: Animated by Hand"') is True
    assert is_cartoon_or_animation_text("Barbour x Wallace & Gromit | Barbour Christmas Film 2026") is True
    assert is_cartoon_or_animation_text("爆款二次元动漫风格广告") is True
    assert is_cartoon_or_animation_text("Luxury Real Person Lifestyle Commercial Transition") is False
    assert is_cartoon_or_animation_text("Photorealistic Kling AI Human Commercial") is False

    # 2. Stage 2 Hard Filter strips cartoons BEFORE AI screening (even with huge views and auto_relax=True)
    candidates = [
        CandidateVideo(
            platform="youtube",
            platform_video_id="prada_anim",
            video_url="https://youtube.com/shorts/prada_anim",
            title='Prada Holiday 2026 | "Drawing Prada: Animated by Hand"',
            views=4_310_000,
            likes=173_000,
            duration_sec=30,
        ),
        CandidateVideo(
            platform="youtube",
            platform_video_id="barbour_clay",
            video_url="https://youtube.com/shorts/barbour_clay",
            title="Barbour x Wallace & Gromit | Barbour Christmas Film 2026",
            views=1_355_000,
            likes=54_000,
            duration_sec=30,
        ),
        CandidateVideo(
            platform="tiktok",
            platform_video_id="real_human_1",
            video_url="https://tiktok.com/@brand/video/real_human_1",
            title="Viral Real Person Luxury Transition Commercial",
            views=820_000,
            likes=41_000,
            duration_sec=18,
        ),
    ]
    out = run_hard_filter(candidates, min_views=50_000, min_likes=2_000, target_count=3, auto_relax=True)
    assert [c.platform_video_id for c in out.selected] == ["real_human_1"]

    # 3. Stage 3 Selection strictly rejects visual-flagged 3D cartoon dolls (e.g. e.l.f.) even with high score
    dna = _led_dna_with_leaky_llm_queries()
    elf_doll = CandidateVideo(
        platform="youtube",
        platform_video_id="elf_doll",
        video_url="https://youtube.com/shorts/elf_doll",
        title="e.l.f. Made To Stand Out",
        views=910_000,
        likes=36_000,
    )
    real_ai = CandidateVideo(
        platform="tiktok",
        platform_video_id="real_ai_human",
        video_url="https://tiktok.com/@a/video/real_ai_human",
        title="Photorealistic AI Woman Commercial Reveal",
        views=600_000,
        likes=28_000,
    )
    selected, _ = select_candidates_for_deep_analysis(
        scored_candidates=[
            _ScreenedCandidate(
                candidate=elf_doll,
                preliminary_score=95,
                visual_creativity_score=95,
                is_same_category=False,
                is_replaceable=True,
                original_featured_item="化妆品",
                is_cartoon_or_animation=True,
                has_realistic_human=False,
            ),
            _ScreenedCandidate(
                candidate=real_ai,
                preliminary_score=88,
                visual_creativity_score=90,
                is_same_category=False,
                is_replaceable=True,
                original_featured_item="时尚手袋",
                is_cartoon_or_animation=False,
                has_realistic_human=True,
            ),
        ],
        product_dna=dna,
        search_strategy="cross_category",
        target_count=3,
    )
    assert [c.platform_video_id for c, _, _ in selected] == ["real_ai_human"]

