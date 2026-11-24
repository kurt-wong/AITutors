/**
 * TeachingScript / Teaching Bundle 的本地类型定义。
 *
 * 权威结构：`Teaching Script Compiler/schema/teaching_script.schema.json`。
 * 播放器只消费其中一部分字段；其余字段按 schema 保留，避免对 API 做过度假设。
 * 公开类型不使用 `any`。
 */

export type ValidationStatus = 'pass' | 'fail';
export type CheckStatus = 'pass' | 'fail' | 'skip';

export type BoardBlockKind =
  | 'heading'
  | 'text'
  | 'math'
  | 'image'
  | 'table'
  | 'callout'
  | 'choice'
  | 'blank';

export type CalloutTone = 'info' | 'warn' | 'answer';
export type EffectType = 'show' | 'highlight' | 'focus' | 'pulse';

export interface BoardBlock {
  id: string;
  kind: BoardBlockKind;
  ref?: string;
  text?: string;
  latex?: string;
  asset_id?: string;
  alt?: string;
  url?: string | null;
  rows?: string[][];
  tone?: CalloutTone;
  label?: string;
  width?: number;
}

export interface TeachingEffect {
  at_ms: number;
  type: EffectType;
  target: string;
  duration_ms?: number;
}

export interface TeachingStep {
  step_id: string;
  goal: string;
  source_refs: string[];
  board: BoardBlock[];
  speech: string;
  subtitle: string;
  duration_ms: number;
  effects: TeachingEffect[];
}

export interface ValidationCheck {
  name: string;
  status: CheckStatus;
  detail?: string;
}

export interface ScriptValidation {
  status: ValidationStatus;
  checks: ValidationCheck[];
  validated_at: string;
}

export interface FinalAnswer {
  display: string;
  value: string;
  answer_type: string;
  grading_rule?: string | null;
  accepted_alternatives?: string[];
  source_refs: string[];
}

export interface TeachingSource {
  kind: 'content_block' | 'answer' | 'explanation_block' | 'asset';
  question_id: string;
  revision_id: string;
  local_id?: string;
  part?: 'stem' | 'option' | 'material';
  index?: number;
  label?: string;
  material_id?: string;
  block_kind?: string;
  line_start?: number | null;
  line_end?: number | null;
  text?: string;
  asset_id?: string;
  storage_path?: string;
  url?: string | null;
  answer_index?: number;
  value_text?: string;
}

export interface TeachingScript {
  script_schema_version: string;
  script_id: string;
  cache_key: string;
  question_id: string;
  revision_id: string;
  revision_number: number;
  language: string;
  prompt_version: string;
  model: string;
  renderer_version: string;
  subject: string;
  source_document_id: string;
  printed_number: string | null;
  question_type: string;
  title: string;
  content_hash: string;
  final_answer: FinalAnswer;
  steps: TeachingStep[];
  sources: Record<string, TeachingSource>;
  created_at: string;
  validation: ScriptValidation;
}

export interface QuestionMeta {
  subject: string;
  source_document_id: string;
  printed_number: string | null;
  question_type: string;
  title: string;
  content_hash: string;
}

export interface BundleAsset {
  asset_id: string;
  storage_path: string;
  mime_type: string;
}

/** `GET /api/teaching-bundles/{question_id}` 的响应体。 */
export interface TeachingBundle {
  question_id: string;
  revision_id: string;
  revision_number: number;
  language: string;
  script: TeachingScript;
  question: QuestionMeta;
  init_step: string;
  from_cache?: boolean;
  assets?: BundleAsset[];
  answer_visibility?: string;
  explanation_visibility?: string;
  renderer_version?: string;
  script_schema_version?: string;
}
