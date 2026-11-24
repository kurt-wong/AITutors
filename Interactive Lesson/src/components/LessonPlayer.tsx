import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import type { TeachingBundle } from '../types';
import {
  createFollowupRequest,
  isParentMessage,
  LESSON_SOURCE,
  postToParent,
} from '../messaging';
import {
  createPlayerState,
  overallProgress,
  playerReducer,
  stepProgress,
  type PlayerAction,
  type PlayerState,
} from '../player/timeline';
import { BoardView } from './BoardView';
import { FollowUpBox } from './FollowUpBox';

interface LessonPlayerProps {
  bundle: TeachingBundle;
  reducedMotion: boolean;
}

const QUESTION_TYPE_LABELS: Record<string, string> = {
  single_choice: '单选题',
  multi_choice: '多选题',
  fill_blank: '填空题',
  essay: '解答题',
  true_false: '判断题',
};

function questionTypeLabel(type: string): string {
  return QUESTION_TYPE_LABELS[type] ?? type;
}

function formatTime(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName.toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
  return target.closest('button, a, [role="button"]') !== null;
}

/** 单个播放器：一个主时钟（performance.now + 单个 rAF 循环），一张黑板。 */
export function LessonPlayer({ bundle, reducedMotion }: LessonPlayerProps) {
  const steps = bundle.script.steps;
  // reducer 需要 steps，用闭包包装（steps 来自不可变 bundle，引用稳定）。
  const reducer = useCallback(
    (previous: PlayerState, action: PlayerAction) => playerReducer(previous, action, steps),
    [steps],
  );
  const [player, rawDispatch] = useReducer(reducer, createPlayerState(steps, bundle.init_step));
  const [followupAnswer, setFollowupAnswer] = useState<string | null>(null);
  const readySentRef = useRef(false);
  const completedSentRef = useRef(false);
  const previousIndexRef = useRef<number | null>(null);

  const currentStep = steps[player.index] ?? steps[0];
  const totalSteps = steps.length;
  const currentProgress = stepProgress(player.elapsedMs, currentStep?.duration_ms ?? 0);
  const totalProgress = overallProgress(player, steps);
  const isPlaying = player.status === 'playing';
  const isEnded = player.status === 'ended';

  // ready：有效脚本首次渲染后发一次。
  useEffect(() => {
    if (readySentRef.current) return;
    readySentRef.current = true;
    postToParent({
      source: LESSON_SOURCE,
      type: 'ready',
      payload: {
        question_id: bundle.question_id,
        revision_id: bundle.revision_id,
        steps: steps.length,
      },
    });
  }, [bundle.question_id, bundle.revision_id, steps.length]);

  // 主时钟：只有 playing 时存在一个 rAF 循环。
  useEffect(() => {
    if (player.status !== 'playing') return;
    let frame = 0;
    let last = performance.now();
    const loop = (now: number) => {
      frame = requestAnimationFrame(loop);
      const delta = now - last;
      last = now;
      rawDispatch({ type: 'tick', deltaMs: delta });
    };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, [player.status]);

  // 步骤变化：清空上一步追问回答，并通知父窗口。
  useEffect(() => {
    const previous = previousIndexRef.current;
    previousIndexRef.current = player.index;
    if (previous === null || previous === player.index) return;
    setFollowupAnswer(null);
    const step = steps[player.index];
    if (!step) return;
    postToParent({
      source: LESSON_SOURCE,
      type: 'step_change',
      payload: {
        step_id: step.step_id,
        index: player.index,
        total: steps.length,
        goal: step.goal,
      },
    });
  }, [player.index, steps]);

  // 播完最后一步：只通知一次，直到离开 ended 态。
  useEffect(() => {
    if (player.status !== 'ended') {
      completedSentRef.current = false;
      return;
    }
    if (completedSentRef.current) return;
    completedSentRef.current = true;
    postToParent({
      source: LESSON_SOURCE,
      type: 'completed',
      payload: { question_id: bundle.question_id, revision_id: bundle.revision_id },
    });
  }, [bundle.question_id, bundle.revision_id, player.status]);

  // 父窗口消息：play / pause / goto_step / followup_answer。
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const data: unknown = event.data;
      if (!isParentMessage(data)) return;
      switch (data.type) {
        case 'play':
          rawDispatch({ type: 'play' });
          break;
        case 'pause':
          rawDispatch({ type: 'pause' });
          break;
        case 'goto_step':
          rawDispatch({ type: 'goto_step', stepId: data.payload.step_id });
          break;
        case 'followup_answer':
          setFollowupAnswer(data.payload.text);
          break;
        default:
          break;
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  // 键盘快捷键；焦点在输入框 / 按钮 / 链接时不拦截。
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (isTypingTarget(event.target)) return;

      switch (event.key) {
        case ' ':
        case 'Spacebar':
          event.preventDefault();
          rawDispatch({ type: 'toggle' });
          break;
        case 'ArrowLeft':
          event.preventDefault();
          rawDispatch({ type: 'prev' });
          break;
        case 'ArrowRight':
          event.preventDefault();
          rawDispatch({ type: 'next' });
          break;
        case 'Home':
          event.preventDefault();
          rawDispatch({ type: 'restart' });
          break;
        case 'End':
          event.preventDefault();
          rawDispatch({ type: 'goto_index', index: steps.length - 1 });
          break;
        case 'r':
        case 'R':
          event.preventDefault();
          rawDispatch({ type: 'replay' });
          break;
        default:
          break;
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [steps.length]);

  const handleFollowup = (question: string) => {
    if (!currentStep) return;
    setFollowupAnswer(null);
    postToParent(createFollowupRequest(bundle, currentStep, question));
  };

  const script = bundle.script;

  return (
    <section className="lesson-player" aria-label="互动讲题播放器">
      <header className="lesson-header" data-testid="lesson-header">
        <div className="header-main">
          <h1 className="lesson-title">{script.title}</h1>
          <div className="header-meta">
            <span className="meta-item">第 {script.printed_number ?? '—'} 题</span>
            <span className="meta-item">{questionTypeLabel(script.question_type)}</span>
            <span className="meta-item">科目：{script.subject}</span>
            <span className="meta-item">revision_number：{script.revision_number}</span>
          </div>
        </div>
        <p className="source-line">来源：Question Core published Revision</p>
      </header>

      <div className="lesson-stage">
        <div className="board-panel" aria-label="当前步骤">
          <BoardView step={currentStep} elapsedMs={player.elapsedMs} reducedMotion={reducedMotion} />
        </div>

        <div className="step-caption">
          <p className="step-goal">{currentStep.goal}</p>
        </div>
      </div>

      <div className="progress">
        <div
          className="progress-track"
          role="progressbar"
          aria-label="本节课进度"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(totalProgress * 100)}
        >
          <div className="progress-fill" style={{ width: `${Math.round(totalProgress * 100)}%` }} />
        </div>
        <div className="progress-meta">
          <span data-testid="step-counter">
            第 {player.index + 1} / {totalSteps} 步
          </span>
          <span data-testid="step-time">
            {formatTime(player.elapsedMs)} / {formatTime(currentStep.duration_ms)}
          </span>
          <span className="progress-step-ratio" aria-hidden="true">
            本步 {Math.round(currentProgress * 100)}%
          </span>
          {isEnded ? (
            <span className="ended-badge" data-testid="ended-badge">
              已播完
            </span>
          ) : null}
        </div>
      </div>

      <div className="controls" role="group" aria-label="播放控制">
        <button
          type="button"
          className="control-button"
          aria-label="上一步"
          onClick={() => rawDispatch({ type: 'prev' })}
          disabled={player.index === 0}
        >
          <span aria-hidden="true">⏮</span>
        </button>
        <button
          type="button"
          className="control-button control-button--primary"
          aria-label={isEnded ? '重新播放' : isPlaying ? '暂停' : '播放'}
          onClick={() => rawDispatch({ type: 'toggle' })}
          data-testid="play-toggle"
        >
          <span aria-hidden="true">{isPlaying ? '⏸' : '▶'}</span>
        </button>
        <button
          type="button"
          className="control-button"
          aria-label="下一步"
          onClick={() => rawDispatch({ type: 'next' })}
          disabled={player.index >= totalSteps - 1}
        >
          <span aria-hidden="true">⏭</span>
        </button>
        <button
          type="button"
          className="control-button"
          aria-label="重播当前步"
          onClick={() => rawDispatch({ type: 'replay' })}
        >
          <span aria-hidden="true">↺</span>
        </button>
      </div>

      <nav className="step-list" aria-label="步骤列表">
        {steps.map((step, index) => (
          <button
            key={step.step_id}
            type="button"
            className={`step-chip${index === player.index ? ' is-current' : ''}`}
            aria-label={`第 ${index + 1} 步：${step.goal}`}
            aria-current={index === player.index ? 'step' : undefined}
            title={step.goal}
            onClick={() => rawDispatch({ type: 'goto_index', index })}
          >
            {index + 1}
          </button>
        ))}
      </nav>

      <div className="sr-only" aria-live="polite" aria-atomic="true" data-testid="step-announcer">
        第 {player.index + 1} 步，共 {totalSteps} 步：{currentStep.goal}
      </div>

      {isEnded ? (
        <div className="ended-banner" role="status" data-testid="lesson-ended">
          <strong>本节讲解已结束</strong>
          <span>最终答案（脚本）：{script.final_answer?.display ?? '—'}</span>
        </div>
      ) : null}

      <FollowUpBox
        stepId={currentStep.step_id}
        answer={followupAnswer}
        onSubmit={handleFollowup}
      />
    </section>
  );
}
