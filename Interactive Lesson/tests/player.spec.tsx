import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { LessonPlayer } from '../src/components/LessonPlayer';
import { createSyntheticBundle, createValidationFailureBundle } from './fixtures/synthetic_bundle';

interface FakeClock {
  advance: (ms: number) => void;
  now: () => number;
}

/** 假 rAF + performance.now：一次 advance 只投递一帧，可精确断言边界。 */
function installFakeClock(start = 1000): FakeClock {
  let now = start;
  let nextId = 1;
  const frames = new Map<number, FrameRequestCallback>();

  vi.spyOn(performance, 'now').mockImplementation(() => now);
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    const id = nextId;
    nextId += 1;
    frames.set(id, callback);
    return id;
  });
  vi.stubGlobal('cancelAnimationFrame', (id: number) => {
    frames.delete(id);
  });

  return {
    advance(ms: number) {
      now += ms;
      const callbacks = [...frames.values()];
      frames.clear();
      for (const callback of callbacks) callback(now);
    },
    now: () => now,
  };
}

function renderPlayer(reducedMotion = false) {
  const bundle = createSyntheticBundle();
  return {
    bundle,
    ...render(<LessonPlayer bundle={bundle} reducedMotion={reducedMotion} />),
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

const VALID_URL =
  '/?question_id=11111111-1111-4111-8111-111111111111&revision_id=22222222-2222-4222-8222-222222222222&api=http://127.0.0.1:8820';

beforeEach(() => {
  window.history.replaceState({}, '', VALID_URL);
  installFakeClock();
});

describe('LessonPlayer 渲染', () => {
  it('renders header, board, KaTeX, and starts paused on init step', () => {
    const { container } = renderPlayer();

    expect(screen.getByTestId('lesson-header')).toBeInTheDocument();
    expect(screen.getByText('99题 · 分苹果（合成测试题）')).toBeInTheDocument();
    expect(screen.getByText('第 99 题')).toBeInTheDocument();
    expect(screen.getByText('单选题')).toBeInTheDocument();
    expect(screen.getByText('revision_number：1')).toBeInTheDocument();
    expect(screen.getByText('来源：Question Core published Revision')).toBeInTheDocument();

    expect(screen.getByTestId('step-counter')).toHaveTextContent('第 1 / 3 步');
    expect(screen.getByTestId('step-time')).toHaveTextContent('0:00 / 0:03');
    expect(screen.getByText('示例：分苹果')).toBeInTheDocument();
    expect(container.querySelectorAll('.katex').length).toBeGreaterThan(0);

    // 初始 paused：选项在 show 之前不可见。
    expect(container.querySelector('[data-block-id="b103"]')).toHaveAttribute('hidden');
    expect(screen.getByRole('button', { name: '播放' })).toBeInTheDocument();
  });

  it('reveals blocks at their show boundary while playing', async () => {
    const user = userEvent.setup();
    const clock = installFakeClock();
    const { container } = renderPlayer();

    await user.click(screen.getByRole('button', { name: '播放' }));

    act(() => clock.advance(499));
    expect(container.querySelector('[data-block-id="b103"]')).toHaveAttribute('hidden');

    act(() => clock.advance(1));
    expect(container.querySelector('[data-block-id="b103"]')).not.toHaveAttribute('hidden');
    expect(container.querySelector('[data-block-id="b104"]')).toHaveAttribute('hidden');

    act(() => clock.advance(500));
    expect(container.querySelector('[data-block-id="b104"]')).not.toHaveAttribute('hidden');
  });

  it('auto-advances steps and stops at the end without looping', async () => {
    const user = userEvent.setup();
    const clock = installFakeClock();
    renderPlayer();

    await user.click(screen.getByRole('button', { name: '播放' }));
    act(() => clock.advance(3000));
    expect(screen.getByTestId('step-counter')).toHaveTextContent('第 2 / 3 步');
    expect(screen.getByText('先算总数，再减去送出的部分。')).toBeInTheDocument();

    act(() => clock.advance(3000));
    expect(screen.getByTestId('step-counter')).toHaveTextContent('第 3 / 3 步');

    act(() => clock.advance(4000));
    expect(screen.getByTestId('lesson-ended')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新播放' })).toBeInTheDocument();
    expect(screen.getByTestId('step-time')).toHaveTextContent('0:04 / 0:04');

    // 已结束：继续推进时钟不会循环回第 1 步。
    act(() => clock.advance(5000));
    expect(screen.getByTestId('step-counter')).toHaveTextContent('第 3 / 3 步');
  });

  it('pause freezes elapsed time', async () => {
    const user = userEvent.setup();
    const clock = installFakeClock();
    renderPlayer();

    await user.click(screen.getByRole('button', { name: '播放' }));
    act(() => clock.advance(500));
    await user.click(screen.getByRole('button', { name: '暂停' }));

    act(() => clock.advance(5000));
    expect(screen.getByTestId('step-counter')).toHaveTextContent('第 1 / 3 步');
    expect(screen.getByTestId('step-time')).toHaveTextContent('0:00 / 0:03');
    expect(screen.getByRole('button', { name: '播放' })).toBeInTheDocument();
  });

  it('next / prev change steps and step chips navigate directly', async () => {
    const user = userEvent.setup();
    renderPlayer();

    await user.click(screen.getByRole('button', { name: '下一步' }));
    expect(screen.getByTestId('step-counter')).toHaveTextContent('第 2 / 3 步');

    await user.click(screen.getByRole('button', { name: '上一步' }));
    expect(screen.getByTestId('step-counter')).toHaveTextContent('第 1 / 3 步');

    await user.click(screen.getByRole('button', { name: '第 3 步：结论：确认最终答案。' }));
    expect(screen.getByTestId('step-counter')).toHaveTextContent('第 3 / 3 步');
    expect(screen.getByTestId('step-announcer')).toHaveTextContent('第 3 步，共 3 步');
  });

  it('replay resets elapsed to zero', async () => {
    const user = userEvent.setup();
    const clock = installFakeClock();
    const { container } = renderPlayer();

    await user.click(screen.getByRole('button', { name: '播放' }));
    act(() => clock.advance(1200));
    expect(container.querySelector('[data-block-id="b104"]')).not.toHaveAttribute('hidden');

    await user.click(screen.getByRole('button', { name: '重播当前步' }));
    expect(screen.getByTestId('step-time')).toHaveTextContent('0:00 / 0:03');
    expect(container.querySelector('[data-block-id="b104"]')).toHaveAttribute('hidden');
  });

  it('renders the unresolved image placeholder with alt and asset id on step 2', async () => {
    const user = userEvent.setup();
    renderPlayer();

    await user.click(screen.getByRole('button', { name: '下一步' }));
    expect(screen.getByTestId('image-placeholder')).toBeInTheDocument();
    expect(screen.getByText('图片未解析')).toBeInTheDocument();
    expect(screen.getByText('img_demo_placeholder')).toBeInTheDocument();
    expect(screen.getByText('示意图')).toBeInTheDocument();
  });
});

describe('键盘与减少动态效果', () => {
  it('supports Space / arrows / Home / End / R shortcuts', async () => {
    const user = userEvent.setup();
    renderPlayer();

    await user.keyboard(' ');
    expect(screen.getByRole('button', { name: '暂停' })).toBeInTheDocument();

    await user.keyboard('{ArrowRight}');
    expect(screen.getByTestId('step-counter')).toHaveTextContent('第 2 / 3 步');

    await user.keyboard('{ArrowLeft}');
    expect(screen.getByTestId('step-counter')).toHaveTextContent('第 1 / 3 步');

    await user.keyboard('{End}');
    expect(screen.getByTestId('step-counter')).toHaveTextContent('第 3 / 3 步');

    await user.keyboard('{Home}');
    expect(screen.getByTestId('step-counter')).toHaveTextContent('第 1 / 3 步');

    await user.keyboard('r');
    expect(screen.getByTestId('step-time')).toHaveTextContent('0:00 / 0:03');
  });

  it('does not hijack keys while typing in the follow-up box', async () => {
    const user = userEvent.setup();
    renderPlayer();

    await user.click(screen.getByLabelText('追问内容'));
    await user.keyboard('a b c');
    expect(screen.getByLabelText('追问内容')).toHaveValue('a b c');
    // 空格没有被当作播放快捷键。
    expect(screen.getByRole('button', { name: '播放' })).toBeInTheDocument();
  });

  it('omits pulse animation and uses static emphasis under reduced motion', async () => {
    const user = userEvent.setup();
    const clock = installFakeClock();
    const { container } = renderPlayer(true);

    await user.click(screen.getByRole('button', { name: '播放' }));

    act(() => clock.advance(200));
    const highlighted = container.querySelector('[data-block-id="b102"]');
    expect(highlighted).toHaveClass('is-highlight');
    expect(highlighted).toHaveClass('is-static-emphasis');

    act(() => clock.advance(1400));
    const pulseTarget = container.querySelector('[data-block-id="b104"]');
    expect(pulseTarget).not.toHaveAttribute('hidden');
    expect(pulseTarget).not.toHaveClass('is-pulse');
  });

  it('applies pulse animation when motion is allowed', async () => {
    const user = userEvent.setup();
    const clock = installFakeClock();
    const { container } = renderPlayer(false);

    await user.click(screen.getByRole('button', { name: '播放' }));
    act(() => clock.advance(1600));

    expect(container.querySelector('[data-block-id="b104"]')).toHaveClass('is-pulse');
  });
});

describe('iframe 消息', () => {
  it('posts ready with step count, step_change on navigation, completed at end', async () => {
    const user = userEvent.setup();
    const clock = installFakeClock();
    const postMessageSpy = vi
      .spyOn(window.parent, 'postMessage')
      .mockImplementation(() => undefined);

    renderPlayer();

    const ready = postMessageSpy.mock.calls
      .map(([message]) => message as { type?: string })
      .find((message) => message.type === 'ready');
    expect(ready).toMatchObject({
      source: 'interactive-lesson',
      type: 'ready',
      payload: {
        question_id: '11111111-1111-4111-8111-111111111111',
        revision_id: '22222222-2222-4222-8222-222222222222',
        steps: 3,
      },
    });

    await user.click(screen.getByRole('button', { name: '下一步' }));
    const stepChange = postMessageSpy.mock.calls
      .map(([message]) => message as { type?: string })
      .find((message) => message.type === 'step_change');
    expect(stepChange).toMatchObject({
      source: 'interactive-lesson',
      type: 'step_change',
      payload: { step_id: 's2', index: 1, total: 3, goal: '分析：先算总数，再减去送出的部分。' },
    });

    await user.click(screen.getByRole('button', { name: '播放' }));
    act(() => clock.advance(9000));
    const completed = postMessageSpy.mock.calls
      .map(([message]) => message as { type?: string })
      .find((message) => message.type === 'completed');
    expect(completed).toMatchObject({
      source: 'interactive-lesson',
      type: 'completed',
      payload: {
        question_id: '11111111-1111-4111-8111-111111111111',
        revision_id: '22222222-2222-4222-8222-222222222222',
      },
    });
  });

  it('handles play / pause / goto_step / followup_answer from the parent', async () => {
    renderPlayer();

    act(() => {
      window.dispatchEvent(
        new MessageEvent('message', { data: { source: 'deeptutor', type: 'play' } }),
      );
    });
    expect(screen.getByRole('button', { name: '暂停' })).toBeInTheDocument();

    act(() => {
      window.dispatchEvent(
        new MessageEvent('message', { data: { source: 'deeptutor', type: 'pause' } }),
      );
    });
    expect(screen.getByRole('button', { name: '播放' })).toBeInTheDocument();

    act(() => {
      window.dispatchEvent(
        new MessageEvent('message', {
          data: { source: 'deeptutor', type: 'goto_step', payload: { step_id: 's3' } },
        }),
      );
    });
    expect(screen.getByTestId('step-counter')).toHaveTextContent('第 3 / 3 步');

    act(() => {
      window.dispatchEvent(
        new MessageEvent('message', {
          data: {
            source: 'deeptutor',
            type: 'followup_answer',
            payload: { text: '因为 5 减 1 等于 4。' },
          },
        }),
      );
    });
    expect(await screen.findByTestId('followup-answer')).toHaveTextContent('因为 5 减 1 等于 4。');

    // 忽略非 deeptutor 消息。
    act(() => {
      window.dispatchEvent(
        new MessageEvent('message', { data: { source: 'other', type: 'play' } }),
      );
    });
    expect(screen.getByRole('button', { name: '播放' })).toBeInTheDocument();
  });
});

describe('App 加载 / 错误 / 校验 / 响应式', () => {
  it('renders lesson-root with responsive marker and reducedMotion from URL', async () => {
    window.history.replaceState({}, '', `${VALID_URL}&reducedMotion=1`);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(createSyntheticBundle())));

    render(<App />);
    expect(await screen.findByTestId('lesson-header')).toBeInTheDocument();

    const root = screen.getByTestId('lesson-root');
    expect(root).toHaveClass('lesson-root');
    expect(root).toHaveAttribute('data-responsive', 'mobile-first');
    expect(root).toHaveAttribute('data-reduced-motion', 'true');
  });

  it('blocks playback when validation.status is not pass', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(createValidationFailureBundle())));

    render(<App />);
    expect(await screen.findByTestId('validation-blocked')).toBeInTheDocument();
    expect(screen.getByText('脚本未通过校验')).toBeInTheDocument();
    expect(screen.getByText('math_renderable')).toBeInTheDocument();
    expect(screen.getByText('board_targets')).toBeInTheDocument();
    expect(screen.queryByLabelText('播放')).not.toBeInTheDocument();
  });

  it('shows the 409 revision conflict message and does not play', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ detail: 'revision not current' }, 409)),
    );

    render(<App />);
    expect(await screen.findByTestId('revision-conflict')).toBeInTheDocument();
    expect(screen.getByText('该 revision 不是当前发布版本')).toBeInTheDocument();
    expect(screen.queryByLabelText('播放')).not.toBeInTheDocument();
  });

  it('shows a retryable network error and recovers on retry', async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('fetch failed'))
      .mockResolvedValueOnce(jsonResponse(createSyntheticBundle()));
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);
    expect(await screen.findByTestId('load-error')).toBeInTheDocument();
    expect(screen.getByText(/无法连接教学脚本服务/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '重试加载' }));
    expect(await screen.findByTestId('lesson-header')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('shows a clear error when question_id is missing', async () => {
    window.history.replaceState({}, '', '/?api=http://127.0.0.1:8820');

    render(<App />);
    expect(await screen.findByTestId('config-error')).toBeInTheDocument();
    expect(screen.getByText('缺少 question_id 参数，无法加载教学脚本。')).toBeInTheDocument();
  });
});
