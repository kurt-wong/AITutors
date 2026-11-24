import { memo, useState } from 'react';
import type { BoardBlock, CalloutTone, TeachingStep } from '../types';
import {
  computeEffectState,
  isBlockVisible,
  type EffectState,
} from '../player/timeline';
import { MathHtml, MathText } from './MathText';

interface BoardViewProps {
  step: TeachingStep;
  elapsedMs: number;
  reducedMotion: boolean;
}

/** 按 step 当前时间渲染整个黑板。纯函数计算可见性/强调，重型公式子树 memo 化。 */
export function BoardView({ step, elapsedMs, reducedMotion }: BoardViewProps) {
  const effectState = computeEffectState(step.effects, elapsedMs);

  return (
    <div className="board" data-testid="board" aria-label="讲解黑板">
      {step.board.map((block) => (
        <BoardBlock
          key={`${step.step_id}:${block.id}`}
          block={block}
          visible={isBlockVisible(block.id, effectState, elapsedMs)}
          className={blockClassName(block, effectState, reducedMotion)}
        />
      ))}
    </div>
  );
}

interface BoardBlockProps {
  block: BoardBlock;
  visible: boolean;
  className: string;
}

const BoardBlock = memo(function BoardBlock({ block, visible, className }: BoardBlockProps) {
  return (
    <div
      className={className}
      hidden={!visible}
      data-block-id={block.id}
      data-block-kind={block.kind}
      data-visible={visible ? 'true' : 'false'}
    >
      <BlockContent block={block} />
    </div>
  );
});

function blockClassName(
  block: BoardBlock,
  effectState: EffectState,
  reducedMotion: boolean,
): string {
  const classes = ['block', `block--${block.kind}`];
  if (effectState.highlight.has(block.id)) {
    classes.push('is-highlight');
    if (reducedMotion) classes.push('is-static-emphasis');
  }
  if (effectState.focus.has(block.id)) {
    classes.push('is-focus');
    if (reducedMotion) classes.push('is-static-emphasis');
  }
  if (effectState.pulse.has(block.id) && !reducedMotion) {
    classes.push('is-pulse');
  }
  return classes.join(' ');
}

function BlockContent({ block }: { block: BoardBlock }) {
  switch (block.kind) {
    case 'heading':
      return (
        <h2 className="block-heading">
          <MathText text={block.text ?? ''} />
        </h2>
      );

    case 'text':
      return (
        <p className="block-text">
          <MathText text={block.text ?? ''} />
        </p>
      );

    case 'math':
      return (
        <div className="block-math math-scroll">
          <MathHtml latex={block.latex ?? ''} displayMode />
        </div>
      );

    case 'image':
      return <BoardImage block={block} />;

    case 'table':
      return <BoardTable rows={block.rows ?? []} />;

    case 'callout':
      return <Callout block={block} />;

    case 'choice':
      return (
        <div className="choice">
          <span className="choice-label" aria-hidden="true">
            {block.label ?? '?'}
          </span>
          <span className="choice-text">
            <MathText text={block.text ?? ''} />
          </span>
        </div>
      );

    case 'blank': {
      const width = Math.min(40, Math.max(2, block.width ?? 8));
      return (
        <div className="blank-row">
          <span className="blank-label">{block.label ?? '空位'}</span>
          <span
            className="blank-line"
            style={{ width: `${width}ch` }}
            aria-label={`空位 ${block.label ?? ''}`}
          />
        </div>
      );
    }

    default:
      return null;
  }
}

function BoardImage({ block }: { block: BoardBlock }) {
  const [failed, setFailed] = useState(false);
  const alt = block.alt && block.alt.length > 0 ? block.alt : '题目图片';
  const showPlaceholder = !block.url || failed;

  return (
    <figure className="block-image">
      {showPlaceholder ? (
        <div
          className="image-placeholder"
          role="img"
          aria-label={`${alt}（图片未解析）`}
          data-testid="image-placeholder"
        >
          <span className="image-placeholder-title">图片未解析</span>
          <span className="image-placeholder-alt">{alt}</span>
          {block.asset_id ? <code className="image-placeholder-asset">{block.asset_id}</code> : null}
        </div>
      ) : (
        <img
          className="block-image-img"
          src={block.url ?? undefined}
          alt={alt}
          loading="lazy"
          onError={() => setFailed(true)}
        />
      )}
    </figure>
  );
}

function BoardTable({ rows }: { rows: string[][] }) {
  if (rows.length === 0) return null;
  const [head, ...body] = rows;

  return (
    <div
      className="table-scroll"
      role="region"
      aria-label="数据表格（可横向滚动）"
      tabIndex={0}
      data-testid="table-scroll"
    >
      <table className="board-table">
        <thead>
          <tr>
            {(head ?? []).map((cell, cellIndex) => (
              <th key={`h-${cellIndex}`} scope="col">
                <MathText text={cell} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, rowIndex) => (
            <tr key={`r-${rowIndex}`}>
              {row.map((cell, cellIndex) => (
                <td key={`c-${cellIndex}`}>
                  <MathText text={cell} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const CALLOUT_TITLES: Record<CalloutTone, string> = {
  info: '提示',
  warn: '注意',
  answer: '答案',
};

function Callout({ block }: { block: BoardBlock }) {
  const tone: CalloutTone = block.tone ?? 'info';
  return (
    <div className={`callout callout--${tone}`} role="note" aria-label={`${CALLOUT_TITLES[tone]}信息`}>
      <span className="callout-title">{CALLOUT_TITLES[tone]}</span>
      <p className="callout-body">
        <MathText text={block.text ?? ''} />
      </p>
    </div>
  );
}
