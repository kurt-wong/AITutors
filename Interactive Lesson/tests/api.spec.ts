import { describe, expect, it } from 'vitest';
import {
  buildBundleUrl,
  failedValidationChecks,
  fetchTeachingBundle,
  TeachingBundleError,
} from '../src/api';
import { createSyntheticBundle, createValidationFailureBundle } from './fixtures/synthetic_bundle';

function fakeResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function fetchReturning(response: Response): typeof fetch {
  return (async () => response) as typeof fetch;
}

async function rejection(promise: Promise<unknown>): Promise<TeachingBundleError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof TeachingBundleError) return error;
    throw error;
  }
  throw new Error('expected the promise to reject');
}

describe('buildBundleUrl', () => {
  it('encodes question id and includes revision/language', () => {
    expect(buildBundleUrl('http://127.0.0.1:8820/', 'q 1', 'r 2')).toBe(
      'http://127.0.0.1:8820/api/teaching-bundles/q%201?revision_id=r+2&language=zh-CN',
    );
  });

  it('appends the short-lived access token when provided', () => {
    expect(buildBundleUrl('http://api', 'q', 'r', 'zh-CN', 'tok.en')).toBe(
      'http://api/api/teaching-bundles/q?revision_id=r&language=zh-CN&access_token=tok.en',
    );
  });

  it('omits revision_id when absent', () => {
    expect(buildBundleUrl('http://api', 'q', null)).toBe(
      'http://api/api/teaching-bundles/q?language=zh-CN',
    );
  });
});

describe('fetchTeachingBundle', () => {
  it('returns the bundle for a 200 response', async () => {
    const bundle = await fetchTeachingBundle({
      apiBase: 'http://api',
      questionId: 'q',
      revisionId: 'r',
      fetchImpl: fetchReturning(fakeResponse(createSyntheticBundle())),
    });
    expect(bundle.script.steps).toHaveLength(3);
  });

  it('maps 409 to the revision conflict message', async () => {
    const error = await rejection(
      fetchTeachingBundle({
        apiBase: 'http://api',
        questionId: 'q',
        fetchImpl: fetchReturning(fakeResponse({ detail: 'old' }, 409)),
      }),
    );
    expect(error.kind).toBe('revision_conflict');
    expect(error.message).toBe('该 revision 不是当前发布版本');
    expect(error.status).toBe(409);
  });

  it('maps 404 and 422 to clear Chinese errors', async () => {
    const notFound = await rejection(
      fetchTeachingBundle({
        apiBase: 'http://api',
        questionId: 'q',
        fetchImpl: fetchReturning(fakeResponse({}, 404)),
      }),
    );
    expect(notFound.kind).toBe('not_found');
    expect(notFound.message).toContain('404');

    const unprocessable = await rejection(
      fetchTeachingBundle({
        apiBase: 'http://api',
        questionId: 'q',
        fetchImpl: fetchReturning(fakeResponse({}, 422)),
      }),
    );
    expect(unprocessable.kind).toBe('unprocessable');
    expect(unprocessable.message).toContain('422');
  });

  it('maps 5xx to a retryable server error', async () => {
    const error = await rejection(
      fetchTeachingBundle({
        apiBase: 'http://api',
        questionId: 'q',
        fetchImpl: fetchReturning(fakeResponse({}, 503)),
      }),
    );
    expect(error.kind).toBe('server');
    expect(error.message).toContain('503');
  });

  it('maps a thrown fetch to a network error', async () => {
    const error = await rejection(
      fetchTeachingBundle({
        apiBase: 'http://api',
        questionId: 'q',
        fetchImpl: (async () => {
          throw new TypeError('fetch failed');
        }) as typeof fetch,
      }),
    );
    expect(error.kind).toBe('network');
    expect(error.message).toContain('无法连接教学脚本服务');
  });

  it('rejects malformed bundle payloads', async () => {
    const error = await rejection(
      fetchTeachingBundle({
        apiBase: 'http://api',
        questionId: 'q',
        fetchImpl: fetchReturning(fakeResponse({ question_id: 'q', revision_id: 'r' })),
      }),
    );
    expect(error.kind).toBe('invalid_response');
  });
});

describe('failedValidationChecks', () => {
  it('lists only failed check names', () => {
    expect(failedValidationChecks(createValidationFailureBundle().script)).toEqual([
      'math_renderable',
      'board_targets',
    ]);
  });
});
