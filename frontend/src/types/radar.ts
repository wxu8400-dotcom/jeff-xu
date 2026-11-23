export interface SearchQueries {
  tiktok: string[];
  instagram: string[];
  youtube: string[];
}

export interface ProductDNA {
  product_name: string;
  category: string;
  physical_form: string;
  core_selling_points: string[];
  target_audience: string;
  usage_scenarios: string[];
  replaceable_visual_slots: string[];
  avoid_patterns: string[];
  search_queries: SearchQueries;
}

export interface ProductAssetMeta {
  filename: string;
  kind: string;
  size_kb?: number;
  chars?: number;
  extracted_frames?: number;
  thumbnail?: string | null;
  error?: string;
}

export interface FunnelStats {
  collected?: number;
  after_hard_filter?: number;
  after_screening?: number;
  analyzed?: number;
  input_tokens?: number;
  output_tokens?: number;
  estimated_cost_cny?: number;
  warnings?: string[];
}

export interface ReplaceabilityAnalysis {
  score: number;
  original_featured_item: string;
  replacement_strategy: string;
  replacement_difficulty: string;
  recommended_workflow: string;
}

export interface VideoStructureAnalysis {
  hook_3s: string;
  pacing_curve: string;
  conversion_cta: string;
  viral_reasons: string[];
}

export interface StoryboardShot {
  shot_no: number;
  time_range: string;
  shot_size: string;
  camera_movement: string;
  original_visual: string;
  adapted_visual_for_product: string;
  audio_sfx: string;
}

export interface ShootingRequirements {
  lighting: string;
  camera_setup: string;
  props_and_scene: string;
  editing_rhythm: string;
  bgm_style: string;
}

export interface CopywritingAnalysis {
  original_transcript: string;
  chinese_translation: string;
  adapted_script_cn: string;
  adapted_script_en: string;
  caption_and_hashtags: string;
}

export interface ChatGPTImagePrompt {
  scene_title: string;
  usage_note: string;
  aspect_ratio: string;
  prompt_en: string;
  prompt_cn: string;
}

export interface KlingVideoPrompt {
  shot_no: number;
  scene_title: string;
  mode: string;
  recommended_params: string;
  prompt_cn: string;
  prompt_en: string;
  negative_prompt: string;
}

export interface VideoDeepAnalysis {
  is_ai_generated: boolean;
  ai_confidence: number;
  ai_detection_reason: string;
  replaceability: ReplaceabilityAnalysis;
  structure: VideoStructureAnalysis;
  storyboard: StoryboardShot[];
  shooting_requirements: ShootingRequirements;
  copywriting: CopywritingAnalysis;
  chatgpt_images_prompts: ChatGPTImagePrompt[];
  kling_prompts: KlingVideoPrompt[];
}

export interface VideoRecord {
  id: string;
  session_id: string;
  platform: "tiktok" | "instagram" | "youtube" | string;
  platform_video_id: string;
  video_url: string;
  cover_url?: string | null;
  author_name?: string | null;
  title: string;
  published_at?: string | null;
  duration_sec?: number | null;
  views: number;
  likes: number;
  comments: number;
  shares: number;
  engagement_rate: number;
  is_ai_generated: boolean;
  ai_confidence: number;
  replaceability_score: number;
  original_featured_item: string;
  analysis_mode: string;
  analysis_json: VideoDeepAnalysis;
  token_usage: { input_tokens?: number; output_tokens?: number };
  created_at: string;
}

export interface ScanSessionSummary {
  id: string;
  history_title: string;
  product_name: string;
  mode: "radar" | "direct_urls" | string;
  status: string;
  progress_percent: number;
  progress_message: string;
  error_message?: string | null;
  platforms: string[];
  funnel_stats: FunnelStats;
  video_count: number;
  created_at: string;
  updated_at: string;
}

export interface ScanSessionDetail {
  id: string;
  history_title: string;
  product_name: string;
  mode: string;
  status: string;
  progress_percent: number;
  progress_message: string;
  error_message?: string | null;
  user_instruction: string;
  platforms: string[];
  filter_config: Record<string, unknown>;
  product_dna?: ProductDNA | null;
  product_assets: ProductAssetMeta[];
  funnel_stats: FunnelStats;
  videos: VideoRecord[];
  created_at: string;
  updated_at: string;
}

export interface AuthStatus {
  password_required: boolean;
  authenticated: boolean;
}

export interface ConfigCheck {
  tikhub_configured: boolean;
  youtube_api_configured: boolean;
  ai_provider: "gemini" | "openai_compatible";
  ai_configured: boolean;
  ai_fast_model: string;
  ai_deep_model: string;
  ai_custom_base_url: boolean;
  database_kind: string;
  ffmpeg_available: boolean;
  mock_mode: boolean;
  password_protected: boolean;
}

export interface ScanProgressEvent {
  session_id: string;
  status: string;
  progress_percent: number;
  progress_message: string;
  error_message?: string | null;
  product_name?: string;
  history_title?: string;
  funnel_stats?: FunnelStats;
}
