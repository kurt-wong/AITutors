import { describe, expect, it } from 'vitest';
import type { TeachingEffect } from '../src/types';
import {
  advancePlayback,
  clampElapsed,
  computeEffectState,
  createPlayerState,
  isBlockVisible,
  overallProgress,
  playerReducer,
  stepProgress,
  type PlayerState,
  type StepTiming,
} from '../src/player/timeline';

const steps: StepTiming[] = [
  { step_id: 's1', duration_ms: 1000 },
  { step_id: 's2', duration_ms: 2000 },
  { step_id: 's3', duration_ms: 3000 },
];

const effects: TeachingEffect[] = [
  { at_ms: 500, type: 'show', target: 'b1' },
  { at_ms: 300, type: 'highlight', target: 'b2', duration_ms: 200 },
  { at_ms: 800, type: 'focus', target: 'b2' },
  { at_ms: 700, type: 'pulse', target: 'b3', duration_ms: 100 },
];

function playing(index = 0, elapsedMs = 0): PlayerState {
  return { index, elapsedMs, status: 'playing' };
}

describe('clampElapsed / stepProgress', () => {
  it('clamps to [0, duration] and rejects non-finite input', () => {
    expect(clampElapsed(500, 1000)).toBe(500);
    expect(clampElapsed(-5, 1000)).toBe(0);
    expect(clampElapsed(1500, 1000)).toBe(1000);
    expect(clampElapsed(Number.NaN, 1000)).toBe(0);
    expect(clampElapsed(500, 0)).toBe(0);
  });

  it('computes per-step progress', () => {
    expect(stepProgress(0, 1000)).toBe(0);
    expect(stepProgress(250, 1000)).toBe(0.25);
    expect(stepProgress(1000, 1000)).toBe(1);
    expect(stepProgress(2000, 1000)).toBe(1);
    expect(stepProgress(10, 0)).toBe(1);
  });

  it('computes overall progress across steps', () => {
    expect(overallProgress({ index: 0, elapsedMs: 0 }, steps)).toBe(0);
    expect(overallProgress({ index: 1, elapsedMs: 1000 }, steps)).toBeCloseTo(1 / 3);
    expect(overallProgress({ index: 2, elapsedMs: 3000 }, steps)).toBe(1);
  });
});

describe('effect visibility at boundaries', () => {
  it('shows a block exactly at its earliest show at_ms', () => {
    expect(isBlockVisible('b1', computeEffectState(effects, 499), 499)).toBe(false);
    expect(isBlockVisible('b1', computeEffectState(effects, 500), 500)).toBe(true);
    expect(isBlockVisible('b1', computeEffectState(effects, 0), 0)).toBe(false);
  });

  it('treats blocks without show effects as visible from step start', () => {
    expect(isBlockVisible('b2', computeEffectState(effects, 0), 0)).toBe(true);
  });

  it('uses the earliest show when several target the same block', () => {
    const multipleShow: TeachingEffect[] = [
      { at_ms: 900, type: 'show', target: 'b1' },
      { at_ms: 400, type: 'show', target: 'b1' },
    ];
    expect(isBlockVisible('b1', computeEffectState(multipleShow, 399), 399)).toBe(false);
    expect(isBlockVisible('b1', computeEffectState(multipleShow, 400), 400)).toBe(true);
  });

  it('activates highlight/focus/pulse only inside their window', () => {
    expect(computeEffectState(effects, 299).highlight.has('b2')).toBe(false);
    expect(computeEffectState(effects, 300).highlight.has('b2')).toBe(true);
    expect(computeEffectState(effects, 499).highlight.has('b2')).toBe(true);
    expect(computeEffectState(effects, 500).highlight.has('b2')).toBe(false);

    expect(computeEffectState(effects, 799).focus.has('b2')).toBe(false);
    expect(computeEffectState(effects, 800).focus.has('b2')).toBe(true);

    expect(computeEffectState(effects, 699).pulse.has('b3')).toBe(false);
    expect(computeEffectState(effects, 700).pulse.has('b3')).toBe(true);
    expect(computeEffectState(effects, 799).pulse.has('b3')).toBe(true);
    expect(computeEffectState(effects, 800).pulse.has('b3')).toBe(false);
  });
});

describe('advancePlayback', () => {
  it('advances exactly when elapsed reaches duration', () => {
    expect(advancePlayback(0, 0, 999, steps)).toEqual({
      index: 0,
      elapsedMs: 999,
      ended: false,
    });
    expect(advancePlayback(0, 0, 1000, steps)).toEqual({
      index: 1,
      elapsedMs: 0,
      ended: false,
    });
  });

  it('spills a long delta into later steps', () => {
    expect(advancePlayback(0, 0, 2500, steps)).toEqual({
      index: 1,
      elapsedMs: 1500,
      ended: false,
    });
  });

  it('stops at the end of the last step without looping', () => {
    expect(advancePlayback(0, 0, 6000, steps)).toEqual({
      index: 2,
      elapsedMs: 3000,
      ended: true,
    });
    expect(advancePlayback(0, 0, 99999, steps)).toEqual({
      index: 2,
      elapsedMs: 3000,
      ended: true,
    });
  });
});

describe('createPlayerState', () => {
  it('starts paused at init_step', () => {
    expect(createPlayerState(steps, 's2')).toEqual({
      index: 1,
      elapsedMs: 0,
      status: 'paused',
    });
    expect(createPlayerState(steps, 'missing')).toEqual({
      index: 0,
      elapsedMs: 0,
      status: 'paused',
    });
  });
});

describe('playerReducer', () => {
  it('play → tick → pause → resume, with pause freezing the clock', () => {
    let state = createPlayerState(steps, 's1');
    state = playerReducer(state, { type: 'play' }, steps);
    expect(state.status).toBe('playing');

    state = playerReducer(state, { type: 'tick', deltaMs: 400 }, steps);
    expect(state).toEqual({ index: 0, elapsedMs: 400, status: 'playing' });

    state = playerReducer(state, { type: 'pause' }, steps);
    state = playerReducer(state, { type: 'tick', deltaMs: 5000 }, steps);
    expect(state).toEqual({ index: 0, elapsedMs: 400, status: 'paused' });

    state = playerReducer(state, { type: 'play' }, steps);
    state = playerReducer(state, { type: 'tick', deltaMs: 600 }, steps);
    expect(state).toEqual({ index: 1, elapsedMs: 0, status: 'playing' });
  });

  it('next / prev seek to step boundaries and reset elapsed', () => {
    let state: PlayerState = { index: 1, elapsedMs: 1500, status: 'paused' };
    state = playerReducer(state, { type: 'next' }, steps);
    expect(state).toEqual({ index: 2, elapsedMs: 0, status: 'paused' });
    state = playerReducer(state, { type: 'prev' }, steps);
    expect(state).toEqual({ index: 1, elapsedMs: 0, status: 'paused' });
    state = playerReducer(state, { type: 'next' }, steps);
    state = playerReducer(state, { type: 'next' }, steps);
    expect(state.index).toBe(2);
  });

  it('replay resets elapsed and plays the current step', () => {
    const state = playerReducer({ index: 2, elapsedMs: 2500, status: 'ended' }, { type: 'replay' }, steps);
    expect(state).toEqual({ index: 2, elapsedMs: 0, status: 'playing' });
  });

  it('goto_step / goto_index seek without changing play state', () => {
    const paused = playerReducer(playing(0, 500), { type: 'goto_step', stepId: 's3' }, steps);
    expect(paused).toEqual({ index: 2, elapsedMs: 0, status: 'playing' });

    const unknown = playerReducer(paused, { type: 'goto_step', stepId: 'nope' }, steps);
    expect(unknown).toBe(paused);

    const ended = playerReducer(
      { index: 2, elapsedMs: 3000, status: 'ended' },
      { type: 'goto_index', index: 0 },
      steps,
    );
    expect(ended).toEqual({ index: 0, elapsedMs: 0, status: 'paused' });
  });

  it('ends on the last step and stays ended until play restarts', () => {
    let state = playing(0, 0);
    state = playerReducer(state, { type: 'tick', deltaMs: 6000 }, steps);
    expect(state).toEqual({ index: 2, elapsedMs: 3000, status: 'ended' });

    const afterTick = playerReducer(state, { type: 'tick', deltaMs: 5000 }, steps);
    expect(afterTick).toBe(state);

    state = playerReducer(state, { type: 'play' }, steps);
    expect(state).toEqual({ index: 0, elapsedMs: 0, status: 'playing' });
  });

  it('ignores ticks while paused', () => {
    const state: PlayerState = { index: 0, elapsedMs: 0, status: 'paused' };
    expect(playerReducer(state, { type: 'tick', deltaMs: 100 }, steps)).toBe(state);
  });
});
