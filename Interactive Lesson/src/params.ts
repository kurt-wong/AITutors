/** URL 参数解析（不改 window 状态，便于测试）。 */

import { DEFAULT_API_BASE } from './api';

export interface LessonParams {
  questionId: string | null;
  revisionId: string | null;
  apiBase: string;
  accessToken: string | null;
  reducedMotion: boolean;
}

const TRUTHY_FLAGS = new Set(['1', 'true', 'yes', 'on']);

export function parseLessonParams(
  search: string,
  defaultApiBase: string = DEFAULT_API_BASE,
): LessonParams {
  const params = new URLSearchParams(search);
  const apiBase = params.get('api')?.trim();
  const questionId = params.get('question_id')?.trim() || null;
  const revisionId = params.get('revision_id')?.trim() || null;
  const accessToken = params.get('access_token')?.trim() || null;
  const reducedMotionRaw = params.get('reducedMotion')?.trim().toLowerCase() ?? '';

  return {
    questionId,
    revisionId,
    apiBase: apiBase || defaultApiBase,
    accessToken,
    reducedMotion: TRUTHY_FLAGS.has(reducedMotionRaw),
  };
}
