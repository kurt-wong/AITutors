import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { LessonPlayer } from '../src/components/LessonPlayer';
import { createSyntheticBundle } from './fixtures/synthetic_bundle';

interface OutboundMessage {
  source?: string;
  type?: string;
  payload?: Record<string, unknown>;
}

function renderPlayer() {
  return render(<LessonPlayer bundle={createSyntheticBundle()} reducedMotion={false} />);
}

function followupRequests(spy: { mock: { calls: unknown[][] } }): OutboundMessage[] {
  return spy.mock.calls
    .map(([message]) => message as OutboundMessage)
    .filter((message) => message.type === 'followup_request');
}

describe('FollowUpBox', () => {
  it('posts followup_request with the current step context and the typed question', async () => {
    const user = userEvent.setup();
    const postMessageSpy = vi
      .spyOn(window.parent, 'postMessage')
      .mockImplementation(() => undefined);

    renderPlayer();

    await user.type(screen.getByLabelText('追问内容'), '为什么 5 减 1 等于 4？');
    await user.click(screen.getByRole('button', { name: '追问这一步' }));

    const requests = followupRequests(postMessageSpy);
    expect(requests).toHaveLength(1);
    expect(requests[0]).toMatchObject({
      source: 'interactive-lesson',
      type: 'followup_request',
      payload: {
        question_id: '11111111-1111-4111-8111-111111111111',
        revision_id: '22222222-2222-4222-8222-222222222222',
        step_id: 's1',
        step_goal: '读题：先看清已知数量，再找问题。',
        speech: '小明有 3 加 2 个苹果，分给小红 1 个，还剩几个？',
        source_refs: ['cb:u99:stem:0', 'cb:u99:option:A:0', 'cb:u99:option:B:0'],
        question: '为什么 5 减 1 等于 4？',
      },
    });
    expect(screen.getByText(/已发送第 s1 步的追问/)).toBeInTheDocument();
  });

  it('uses the step that is current at submit time', async () => {
    const user = userEvent.setup();
    const postMessageSpy = vi
      .spyOn(window.parent, 'postMessage')
      .mockImplementation(() => undefined);

    renderPlayer();

    await user.click(screen.getByRole('button', { name: '下一步' }));
    await user.type(screen.getByLabelText('追问内容'), '表格里的总数怎么来的？');
    await user.click(screen.getByRole('button', { name: '追问这一步' }));

    const requests = followupRequests(postMessageSpy);
    expect(requests).toHaveLength(1);
    expect(requests[0]?.payload).toMatchObject({
      step_id: 's2',
      step_goal: '分析：先算总数，再减去送出的部分。',
      question: '表格里的总数怎么来的？',
    });
  });

  it('does not send empty questions', async () => {
    const user = userEvent.setup();
    const postMessageSpy = vi
      .spyOn(window.parent, 'postMessage')
      .mockImplementation(() => undefined);

    renderPlayer();

    const submit = screen.getByRole('button', { name: '追问这一步' });
    expect(submit).toBeDisabled();

    await user.type(screen.getByLabelText('追问内容'), '   ');
    expect(submit).toBeDisabled();
    await user.click(submit);

    expect(followupRequests(postMessageSpy)).toHaveLength(0);
  });
});
