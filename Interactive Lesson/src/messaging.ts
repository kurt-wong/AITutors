/** iframe postMessage 协议（见 docs/CONTRACT.md §5）。 */

import type { TeachingBundle, TeachingStep } from './types';

export const LESSON_SOURCE = 'interactive-lesson';
export const PARENT_SOURCE = 'deeptutor';

export interface ReadyPayload {
  question_id: string;
  revision_id: string;
  steps: number;
}

export interface StepChangePayload {
  step_id: string;
  index: number;
  total: number;
  goal: string;
}

export interface CompletedPayload {
  question_id: string;
  revision_id: string;
}

export interface FollowupRequestPayload {
  question_id: string;
  revision_id: string;
  step_id: string;
  step_goal: string;
  speech: string;
  source_refs: string[];
  /**
   * 用户输入的问题文本。
   * 契约只列了步骤上下文，没有给输入文本留字段；父窗口需要知道问的是什么，
   * 故追加 `question`（不修改其它字段的既有语义）。
   */
  question: string;
}

export type LessonOutboundMessage =
  | { source: typeof LESSON_SOURCE; type: 'ready'; payload: ReadyPayload }
  | { source: typeof LESSON_SOURCE; type: 'step_change'; payload: StepChangePayload }
  | { source: typeof LESSON_SOURCE; type: 'completed'; payload: CompletedPayload }
  | {
      source: typeof LESSON_SOURCE;
      type: 'followup_request';
      payload: FollowupRequestPayload;
    };

export type ParentMessage =
  | { source: typeof PARENT_SOURCE; type: 'play' }
  | { source: typeof PARENT_SOURCE; type: 'pause' }
  | { source: typeof PARENT_SOURCE; type: 'goto_step'; payload: { step_id: string } }
  | {
      source: typeof PARENT_SOURCE;
      type: 'followup_answer';
      payload: { text: string };
    };

export function postToParent(
  message: LessonOutboundMessage,
  target: Window = window.parent,
): void {
  target.postMessage(message, '*');
}

export function createFollowupRequest(
  bundle: TeachingBundle,
  step: TeachingStep,
  question: string,
): LessonOutboundMessage {
  return {
    source: LESSON_SOURCE,
    type: 'followup_request',
    payload: {
      question_id: bundle.question_id,
      revision_id: bundle.revision_id,
      step_id: step.step_id,
      step_goal: step.goal,
      speech: step.speech,
      source_refs: [...step.source_refs],
      question,
    },
  };
}

/** 校验父窗口消息；非 deeptutor / 结构不对的消息一律忽略。 */
export function isParentMessage(value: unknown): value is ParentMessage {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Record<string, unknown>;
  if (candidate.source !== PARENT_SOURCE || typeof candidate.type !== 'string') return false;

  switch (candidate.type) {
    case 'play':
    case 'pause':
      return true;
    case 'goto_step': {
      const payload = candidate.payload;
      return (
        typeof payload === 'object' &&
        payload !== null &&
        typeof (payload as Record<string, unknown>).step_id === 'string'
      );
    }
    case 'followup_answer': {
      const payload = candidate.payload;
      return (
        typeof payload === 'object' &&
        payload !== null &&
        typeof (payload as Record<string, unknown>).text === 'string'
      );
    }
    default:
      return false;
  }
}
