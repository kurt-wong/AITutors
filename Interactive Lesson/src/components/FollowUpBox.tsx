import { useState, type FormEvent } from 'react';

interface FollowUpBoxProps {
  stepId: string;
  /** 父窗口回传的答案；null 表示尚未回答。 */
  answer: string | null;
  onSubmit: (question: string) => void;
}

/**
 * 最小追问入口：只把问题交给父窗口，不在播放器里作答。
 * 父窗口通过 `followup_answer` 回传文本后由 LessonPlayer 传入展示。
 */
export function FollowUpBox({ stepId, answer, onSubmit }: FollowUpBoxProps) {
  const [text, setText] = useState('');
  const [sentQuestion, setSentQuestion] = useState<string | null>(null);
  const trimmed = text.trim();

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (trimmed.length === 0) return;
    onSubmit(trimmed);
    setSentQuestion(trimmed);
    setText('');
  };

  return (
    <form className="followup" aria-label="追问这一步" onSubmit={handleSubmit}>
      <label className="followup-label" htmlFor="followup-input">
        追问这一步
      </label>
      <textarea
        id="followup-input"
        className="followup-input"
        aria-label="追问内容"
        placeholder="写下你不确定的地方…"
        rows={2}
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      <div className="followup-actions">
        <button type="submit" className="followup-submit" disabled={trimmed.length === 0}>
          追问这一步
        </button>
        <span className="followup-status" role="status" aria-live="polite">
          {answer
            ? '已收到回答，见下方。'
            : sentQuestion
              ? `已发送第 ${stepId} 步的追问，等待回答…`
              : '问题只发送给父窗口，由外部作答。'}
        </span>
      </div>
      {answer ? (
        <div className="followup-answer" data-testid="followup-answer" role="note" aria-label="追问回答">
          <span className="followup-answer-title">回答</span>
          <p>{answer}</p>
        </div>
      ) : null}
    </form>
  );
}
