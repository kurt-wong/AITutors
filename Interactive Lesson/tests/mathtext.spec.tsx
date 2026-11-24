import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MathHtml, MathText, splitMathText } from '../src/components/MathText';

describe('splitMathText', () => {
  it('splits inline math while keeping surrounding text', () => {
    expect(splitMathText('已知 $ x + 1 $，求值')).toEqual([
      { type: 'text', value: '已知 ', display: false },
      { type: 'math', value: ' x + 1 ', display: false },
      { type: 'text', value: '，求值', display: false },
    ]);
  });

  it('supports display math with $$', () => {
    expect(splitMathText('$$ x = 1 $$')).toEqual([
      { type: 'math', value: ' x = 1 ', display: true },
    ]);
  });

  it('treats escaped dollars as literal text', () => {
    expect(splitMathText('价格 \\$5，公式 $x$')).toEqual([
      { type: 'text', value: '价格 $5，公式 ', display: false },
      { type: 'math', value: 'x', display: false },
    ]);
  });

  it('leaves unclosed dollar signs as plain text', () => {
    expect(splitMathText('未闭合 $x')).toEqual([
      { type: 'text', value: '未闭合 $x', display: false },
    ]);
  });
});

describe('MathHtml', () => {
  it('renders valid LaTeX through KaTeX', () => {
    const { container } = render(<MathHtml latex="x^2 + 1" />);
    expect(container.querySelector('.katex')).not.toBeNull();
  });

  it('does not crash on invalid LaTeX', () => {
    const { container } = render(<MathHtml latex="\\frac{1}{" />);
    expect(container.querySelector('.math-html, .math-fallback')).not.toBeNull();
  });
});

describe('MathText', () => {
  it('renders mixed text and inline math', () => {
    const { container } = render(<MathText text="总数是 $3 + 2$ 个。" />);
    expect(container.textContent).toContain('总数是');
    expect(container.querySelectorAll('.katex').length).toBe(1);
  });
});
