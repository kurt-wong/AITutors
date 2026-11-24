import { useEffect, useState } from 'react';
import {
  failedValidationChecks,
  fetchTeachingBundle,
  TeachingBundleError,
} from './api';
import { LessonPlayer } from './components/LessonPlayer';
import { useReducedMotion } from './hooks/useReducedMotion';
import { parseLessonParams } from './params';
import type { TeachingBundle } from './types';

type AppState =
  | { status: 'loading' }
  | { status: 'config_error'; message: string }
  | { status: 'ready'; bundle: TeachingBundle }
  | { status: 'validation_blocked'; failedChecks: string[] }
  | { status: 'revision_conflict'; message: string }
  | { status: 'error'; message: string };

export default function App() {
  const [params] = useState(() => parseLessonParams(window.location.search));
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<AppState>({ status: 'loading' });
  const mediaReducedMotion = useReducedMotion();
  const reducedMotion = mediaReducedMotion || params.reducedMotion;

  useEffect(() => {
    if (!params.questionId) {
      setState({
        status: 'config_error',
        message: '缺少 question_id 参数，无法加载教学脚本。',
      });
      return;
    }

    const controller = new AbortController();
    setState({ status: 'loading' });

    fetchTeachingBundle({
      apiBase: params.apiBase,
      questionId: params.questionId,
      revisionId: params.revisionId,
      signal: controller.signal,
    })
      .then((bundle) => {
        if (controller.signal.aborted) return;
        if (bundle.script.validation.status !== 'pass') {
          setState({
            status: 'validation_blocked',
            failedChecks: failedValidationChecks(bundle.script),
          });
          return;
        }
        setState({ status: 'ready', bundle });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof TeachingBundleError && error.kind === 'revision_conflict') {
          setState({ status: 'revision_conflict', message: error.message });
          return;
        }
        const message =
          error instanceof Error && error.message.length > 0
            ? error.message
            : '加载教学脚本时发生未知错误，请重试。';
        setState({ status: 'error', message });
      });

    return () => controller.abort();
  }, [params, attempt]);

  return (
    <main
      className="lesson-root"
      data-testid="lesson-root"
      data-responsive="mobile-first"
      data-reduced-motion={reducedMotion ? 'true' : 'false'}
    >
      {state.status === 'loading' ? (
        <section className="state-screen" role="status" aria-live="polite">
          <p className="state-title">正在加载教学脚本…</p>
        </section>
      ) : null}

      {state.status === 'config_error' ? (
        <section className="state-screen state-screen--error" data-testid="config-error">
          <h1 className="state-title">无法播放</h1>
          <p>{state.message}</p>
          <p className="state-hint">
            请在地址中加入{' '}
            <code>?question_id=&lt;uuid&gt;&amp;revision_id=&lt;uuid&gt;&amp;api=http://127.0.0.1:8820</code>
            。
          </p>
        </section>
      ) : null}

      {state.status === 'revision_conflict' ? (
        <section
          className="state-screen state-screen--error"
          data-testid="revision-conflict"
          aria-live="polite"
        >
          <h1 className="state-title">{state.message}</h1>
          <p>播放器不会播放旧 revision 的讲题脚本，请从当前发布页面重新进入。</p>
        </section>
      ) : null}

      {state.status === 'validation_blocked' ? (
        <section
          className="state-screen state-screen--error"
          data-testid="validation-blocked"
          aria-live="polite"
        >
          <h1 className="state-title">脚本未通过校验</h1>
          <p>该讲题脚本未通过编译校验，播放器不会播放。</p>
          <p className="state-hint">
            未通过的检查项：
            <span />
          </p>
          <ul className="failed-checks">
            {state.failedChecks.length > 0 ? (
              state.failedChecks.map((name) => <li key={name}>{name}</li>)
            ) : (
              <li>（验证结果未给出失败项名称）</li>
            )}
          </ul>
        </section>
      ) : null}

      {state.status === 'error' ? (
        <section className="state-screen state-screen--error" data-testid="load-error" role="alert">
          <h1 className="state-title">加载失败</h1>
          <p>{state.message}</p>
          <button
            type="button"
            className="retry-button"
            onClick={() => setAttempt((value) => value + 1)}
          >
            重试加载
          </button>
        </section>
      ) : null}

      {state.status === 'ready' ? (
        <LessonPlayer bundle={state.bundle} reducedMotion={reducedMotion} />
      ) : null}
    </main>
  );
}
