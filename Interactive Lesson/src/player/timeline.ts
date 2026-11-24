/**
 * 纯播放时间线：不碰 DOM、不碰计时器。
 *
 * 组件只在 requestAnimationFrame 回调里把「本帧 delta」交给 `playerReducer`，
 * 所有可见性 / 强调 / 自动进下一步 / 结束态判断都在这里完成，便于用假时钟单测。
 */

import type { TeachingEffect } from '../types';

export interface StepTiming {
  step_id: string;
  duration_ms: number;
  effects?: readonly TeachingEffect[];
}

export type PlaybackStatus = 'paused' | 'playing' | 'ended';

export interface PlayerState {
  /** 当前 step 下标（0-based）。 */
  index: number;
  /** 当前 step 内已播放毫秒数。 */
  elapsedMs: number;
  status: PlaybackStatus;
}

export interface EffectState {
  /** block id -> 最早 show 的 at_ms；没有 show 的 block 不在表内。 */
  showAt: ReadonlyMap<string, number>;
  highlight: ReadonlySet<string>;
  focus: ReadonlySet<string>;
  pulse: ReadonlySet<string>;
}

export interface AdvanceResult {
  index: number;
  elapsedMs: number;
  ended: boolean;
}

export type PlayerAction =
  | { type: 'play' }
  | { type: 'pause' }
  | { type: 'toggle' }
  | { type: 'tick'; deltaMs: number }
  | { type: 'next' }
  | { type: 'prev' }
  | { type: 'replay' }
  | { type: 'goto_index'; index: number }
  | { type: 'goto_step'; stepId: string }
  | { type: 'restart' };

/** 把 step 内时间夹到 [0, duration]。非法输入按 0 处理。 */
export function clampElapsed(elapsedMs: number, durationMs: number): number {
  if (!Number.isFinite(elapsedMs) || elapsedMs <= 0) return 0;
  const duration = Number.isFinite(durationMs) && durationMs > 0 ? durationMs : 0;
  if (duration === 0) return 0;
  return Math.min(elapsedMs, duration);
}

/** 当前 step 的进度，0..1。 */
export function stepProgress(elapsedMs: number, durationMs: number): number {
  const duration = Number.isFinite(durationMs) && durationMs > 0 ? durationMs : 0;
  if (duration === 0) return Number.isFinite(elapsedMs) && elapsedMs > 0 ? 1 : 0;
  return clampElapsed(elapsedMs, duration) / duration;
}

/** 整节课的进度（含已走完的 step），0..1。 */
export function overallProgress(
  state: Pick<PlayerState, 'index' | 'elapsedMs'>,
  steps: readonly StepTiming[],
): number {
  const total = steps.reduce((sum, step) => sum + Math.max(0, step.duration_ms), 0);
  if (total <= 0 || steps.length === 0) return 0;
  const safeIndex = clampIndex(state.index, steps.length);
  let done = 0;
  for (let i = 0; i < safeIndex; i += 1) {
    done += Math.max(0, steps[i]?.duration_ms ?? 0);
  }
  done += clampElapsed(state.elapsedMs, steps[safeIndex]?.duration_ms ?? 0);
  return Math.min(1, done / total);
}

export function clampIndex(index: number, total: number): number {
  if (!Number.isFinite(index) || index <= 0 || total <= 0) return 0;
  return Math.min(Math.floor(index), total - 1);
}

/** 汇总一个 step 内所有 effect 在 `elapsedMs` 时刻的状态。 */
export function computeEffectState(
  effects: readonly TeachingEffect[] | undefined,
  elapsedMs: number,
): EffectState {
  const showAt = new Map<string, number>();
  const highlight = new Set<string>();
  const focus = new Set<string>();
  const pulse = new Set<string>();

  for (const effect of effects ?? []) {
    if (effect.type === 'show') {
      const at = Math.max(0, Number.isFinite(effect.at_ms) ? effect.at_ms : 0);
      const previous = showAt.get(effect.target);
      if (previous === undefined || at < previous) showAt.set(effect.target, at);
      continue;
    }
    if (!isEffectActive(effect, elapsedMs)) continue;
    if (effect.type === 'highlight') highlight.add(effect.target);
    else if (effect.type === 'focus') focus.add(effect.target);
    else if (effect.type === 'pulse') pulse.add(effect.target);
  }

  return { showAt, highlight, focus, pulse };
}

/** 没有 show effect 的 block 从 step 起点可见；有 show 的从最早的 at_ms 起可见。 */
export function isBlockVisible(
  blockId: string,
  effectState: Pick<EffectState, 'showAt'>,
  elapsedMs: number,
): boolean {
  const at = effectState.showAt.get(blockId);
  return at === undefined || elapsedMs >= at;
}

function isEffectActive(effect: TeachingEffect, elapsedMs: number): boolean {
  const at = Math.max(0, Number.isFinite(effect.at_ms) ? effect.at_ms : 0);
  if (elapsedMs < at) return false;
  if (effect.duration_ms === undefined) return true;
  if (!Number.isFinite(effect.duration_ms)) return true;
  return elapsedMs < at + Math.max(0, effect.duration_ms);
}

/**
 * 从 `index / elapsedMs` 起推进 `deltaMs`，处理跨 step 与结束态。
 * 规则：elapsed >= duration 即进入下一步；最后一步到点后 ended，不循环。
 */
export function advancePlayback(
  index: number,
  elapsedMs: number,
  deltaMs: number,
  steps: readonly StepTiming[],
): AdvanceResult {
  if (steps.length === 0) return { index: 0, elapsedMs: 0, ended: true };
  let i = clampIndex(index, steps.length);
  let elapsed = clampElapsed(elapsedMs, steps[i]?.duration_ms ?? 0);
  let remaining = Number.isFinite(deltaMs) && deltaMs > 0 ? deltaMs : 0;

  while (remaining > 0) {
    const duration = Math.max(0, steps[i]?.duration_ms ?? 0);
    const room = duration - elapsed;
    if (room > remaining) {
      elapsed += remaining;
      remaining = 0;
      break;
    }
    remaining -= Math.max(0, room);
    if (i >= steps.length - 1) {
      return { index: i, elapsedMs: duration, ended: true };
    }
    i += 1;
    elapsed = 0;
    if (remaining === 0) break;
  }

  const duration = Math.max(0, steps[i]?.duration_ms ?? 0);
  const ended = i === steps.length - 1 && elapsed >= duration;
  return {
    index: i,
    elapsedMs: ended ? duration : clampElapsed(elapsed, duration),
    ended,
  };
}

/** 初始状态：停在 `init_step`（找不到则第 0 步），等待用户播放。 */
export function createPlayerState(
  steps: readonly StepTiming[],
  initStepId?: string | null,
): PlayerState {
  const found = initStepId ? steps.findIndex((step) => step.step_id === initStepId) : -1;
  return { index: found >= 0 ? found : 0, elapsedMs: 0, status: 'paused' };
}

export function playerReducer(
  state: PlayerState,
  action: PlayerAction,
  steps: readonly StepTiming[],
): PlayerState {
  if (steps.length === 0) return state;

  switch (action.type) {
    case 'play':
      // 用户主动按播放时，从结束态重新开始整节课；不自动循环。
      if (state.status === 'ended') return { index: 0, elapsedMs: 0, status: 'playing' };
      return state.status === 'playing' ? state : { ...state, status: 'playing' };

    case 'pause':
      return state.status === 'playing' ? { ...state, status: 'paused' } : state;

    case 'toggle':
      return playerReducer(
        state,
        { type: state.status === 'playing' ? 'pause' : 'play' },
        steps,
      );

    case 'tick': {
      if (state.status !== 'playing') return state;
      const advanced = advancePlayback(state.index, state.elapsedMs, action.deltaMs, steps);
      return {
        index: advanced.index,
        elapsedMs: advanced.elapsedMs,
        status: advanced.ended ? 'ended' : 'playing',
      };
    }

    case 'next': {
      if (state.index >= steps.length - 1) return state;
      return {
        index: state.index + 1,
        elapsedMs: 0,
        status: state.status === 'ended' ? 'paused' : state.status,
      };
    }

    case 'prev': {
      const index = state.index > 0 ? state.index - 1 : 0;
      return {
        index,
        elapsedMs: 0,
        status: state.status === 'ended' ? 'paused' : state.status,
      };
    }

    case 'replay':
      return { index: state.index, elapsedMs: 0, status: 'playing' };

    case 'goto_index':
      return seekTo(state, action.index, steps);

    case 'goto_step': {
      const index = steps.findIndex((step) => step.step_id === action.stepId);
      return index < 0 ? state : seekTo(state, index, steps);
    }

    case 'restart':
      return seekTo(state, 0, steps);

    default:
      return state;
  }
}

function seekTo(
  state: PlayerState,
  index: number,
  steps: readonly StepTiming[],
): PlayerState {
  return {
    index: clampIndex(index, steps.length),
    elapsedMs: 0,
    status: state.status === 'playing' ? 'playing' : 'paused',
  };
}
