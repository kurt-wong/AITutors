/** Teaching Bundle 拉取与错误映射。只负责 HTTP，不含 UI。 */

import type { TeachingBundle, TeachingScript } from './types';

export const DEFAULT_API_BASE = 'http://127.0.0.1:8820';
export const DEFAULT_LANGUAGE = 'zh-CN';

export type BundleErrorKind =
  | 'revision_conflict'
  | 'not_found'
  | 'unprocessable'
  | 'network'
  | 'server'
  | 'invalid_response';

export class TeachingBundleError extends Error {
  readonly kind: BundleErrorKind;
  readonly status: number | null;

  constructor(kind: BundleErrorKind, message: string, status: number | null = null) {
    super(message);
    this.name = 'TeachingBundleError';
    this.kind = kind;
    this.status = status;
  }
}

export function buildBundleUrl(
  apiBase: string,
  questionId: string,
  revisionId: string | null | undefined,
  language: string = DEFAULT_LANGUAGE,
  accessToken?: string | null,
): string {
  const base = apiBase.replace(/\/+$/, '');
  const query = new URLSearchParams();
  if (revisionId) query.set('revision_id', revisionId);
  query.set('language', language);
  if (accessToken) query.set('access_token', accessToken);
  return `${base}/api/teaching-bundles/${encodeURIComponent(questionId)}?${query.toString()}`;
}

export interface FetchBundleOptions {
  apiBase: string;
  questionId: string;
  revisionId?: string | null;
  language?: string;
  accessToken?: string | null;
  signal?: AbortSignal;
  /** 测试注入点；缺省使用全局 fetch。 */
  fetchImpl?: typeof fetch;
}

export async function fetchTeachingBundle(options: FetchBundleOptions): Promise<TeachingBundle> {
  const fetchImpl = options.fetchImpl ?? globalThis.fetch;
  if (typeof fetchImpl !== 'function') {
    throw new TeachingBundleError('network', '当前环境不支持网络请求，无法加载教学脚本。');
  }

  const url = buildBundleUrl(
    options.apiBase,
    options.questionId,
    options.revisionId,
    options.language ?? DEFAULT_LANGUAGE,
    options.accessToken,
  );

  let response: Response;
  try {
    response = await fetchImpl(url, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: options.signal,
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new TeachingBundleError(
      'network',
      '无法连接教学脚本服务，请确认 API 地址与网络后重试。',
    );
  }

  if (!response.ok) {
    throw mapHttpStatus(response.status);
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new TeachingBundleError('invalid_response', '服务端返回的数据不是有效 JSON。');
  }

  if (!isTeachingBundle(data)) {
    throw new TeachingBundleError(
      'invalid_response',
      '服务端返回的教学脚本数据格式不正确（缺少 question/script/steps/validation）。',
    );
  }
  return data;
}

function mapHttpStatus(status: number): TeachingBundleError {
  if (status === 409) {
    return new TeachingBundleError(
      'revision_conflict',
      '该 revision 不是当前发布版本',
      status,
    );
  }
  if (status === 404) {
    return new TeachingBundleError(
      'not_found',
      '未找到该题目的教学脚本（HTTP 404），请确认题目 ID 与发布状态。',
      status,
    );
  }
  if (status === 422) {
    return new TeachingBundleError(
      'unprocessable',
      '教学脚本服务拒绝了请求参数（HTTP 422），请检查 question_id / revision_id。',
      status,
    );
  }
  if (status >= 500) {
    return new TeachingBundleError(
      'server',
      `教学脚本服务暂时不可用（HTTP ${status}），请稍后重试。`,
      status,
    );
  }
  return new TeachingBundleError(
    'server',
    `教学脚本服务返回异常状态（HTTP ${status}）。`,
    status,
  );
}

/** 返回 validation.status === 'fail' 的检查项名称。 */
export function failedValidationChecks(script: TeachingScript): string[] {
  return script.validation.checks
    .filter((check) => check.status === 'fail')
    .map((check) => check.name);
}

function isAbortError(error: unknown): boolean {
  if (error instanceof DOMException) return error.name === 'AbortError';
  return (
    typeof error === 'object' &&
    error !== null &&
    'name' in error &&
    (error as { name?: unknown }).name === 'AbortError'
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * 宽松但足够安全的响应校验：只要求播放器真正会用到的嵌套结构存在。
 * 具体字段的类型错误留给渲染层做容错（例如缺 text 时渲染空字符串）。
 */
function isTeachingBundle(value: unknown): value is TeachingBundle {
  if (!isRecord(value)) return false;
  if (typeof value.question_id !== 'string' || typeof value.revision_id !== 'string') {
    return false;
  }
  if (!isRecord(value.question)) return false;
  if (!isRecord(value.script)) return false;

  const script = value.script;
  if (!Array.isArray(script.steps) || script.steps.length === 0) return false;
  if (!isRecord(script.validation) || typeof script.validation.status !== 'string') {
    return false;
  }
  if (!Array.isArray(script.validation.checks)) return false;
  return script.steps.every(
    (step) =>
      isRecord(step) &&
      typeof step.step_id === 'string' &&
      typeof step.duration_ms === 'number' &&
      Array.isArray(step.board),
  );
}
