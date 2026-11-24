import { memo, useMemo } from 'react';
import { renderToString } from 'katex';

export interface MathSegment {
  type: 'text' | 'math';
  value: string;
  /** `$$...$$` 使用 display mode。 */
  display: boolean;
}

/**
 * 把含 `$...$` / `$$...$$` 的文本拆成文本段与公式段。
 * 支持反斜杠转义（`\$` 视为字面美元符），未闭合的 `$` 保留为普通文本。
 */
export function splitMathText(text: string): MathSegment[] {
  const segments: MathSegment[] = [];
  let buffer = '';
  let index = 0;

  const flush = () => {
    if (buffer.length > 0) {
      segments.push({ type: 'text', value: buffer, display: false });
      buffer = '';
    }
  };

  while (index < text.length) {
    const char = text[index];

    if (char === '\\' && text[index + 1] === '$') {
      buffer += '$';
      index += 2;
      continue;
    }

    if (char === '$') {
      const marker = text[index + 1] === '$' ? '$$' : '$';
      const start = index + marker.length;
      let end = start;

      while (end < text.length) {
        if (text[end] === '\\') {
          end += 2;
          continue;
        }
        if (text.startsWith(marker, end)) break;
        end += 1;
      }

      if (end < text.length && end > start) {
        flush();
        segments.push({ type: 'math', value: text.slice(start, end), display: marker === '$$' });
        index = end + marker.length;
        continue;
      }
    }

    buffer += char;
    index += 1;
  }

  flush();
  if (segments.length === 0) {
    segments.push({ type: 'text', value: text, display: false });
  }
  return segments;
}

interface MathHtmlProps {
  latex: string;
  displayMode?: boolean;
  className?: string;
}

/**
 * KaTeX 渲染小部件：HTML 由 KaTeX 生成，通过 dangerouslySetInnerHTML 注入。
 * 非法 LaTeX 在 throwOnError:false 下返回错误渲染；极端情况下抛错则退回纯文本。
 */
export const MathHtml = memo(function MathHtml({
  latex,
  displayMode = false,
  className = '',
}: MathHtmlProps) {
  const html = useMemo(() => renderMath(latex, displayMode), [latex, displayMode]);

  if (html === null) {
    return (
      <code className={`math-fallback ${className}`.trim()} title="无法渲染的公式">
        {latex}
      </code>
    );
  }

  return (
    <span
      className={`math-html ${displayMode ? 'math-html--display' : 'math-html--inline'} ${className}`.trim()}
      data-latex={latex}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
});

interface MathTextProps {
  text: string;
  className?: string;
}

/** 文本 + 内联/独立公式混排。 */
export const MathText = memo(function MathText({ text, className = '' }: MathTextProps) {
  const segments = useMemo(() => splitMathText(text), [text]);
  return (
    <span className={`math-text ${className}`.trim()}>
      {segments.map((segment, index) =>
        segment.type === 'math' ? (
          <MathHtml
            key={`m-${index}`}
            latex={segment.value}
            displayMode={segment.display}
            className={segment.display ? 'math-own-line' : 'math-inline'}
          />
        ) : (
          <span key={`t-${index}`}>{segment.value}</span>
        ),
      )}
    </span>
  );
});

function renderMath(latex: string, displayMode: boolean): string | null {
  try {
    return renderToString(latex, {
      displayMode,
      throwOnError: false,
      strict: 'ignore',
      trust: false,
    });
  } catch {
    return null;
  }
}
