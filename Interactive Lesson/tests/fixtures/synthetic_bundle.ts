import type { TeachingBundle } from '../../src/types';

/**
 * 合成测试夹具：内容为自编的「分苹果」小例子，不含任何真实试卷内容。
 * 结构遵循 teaching_script.schema.json（duration_ms >= 3000，block/effect 字段齐全）。
 */
const BASE_BUNDLE: TeachingBundle = {
  question_id: '11111111-1111-4111-8111-111111111111',
  revision_id: '22222222-2222-4222-8222-222222222222',
  revision_number: 1,
  language: 'zh-CN',
  from_cache: false,
  init_step: 's1',
  question: {
    subject: '数学',
    source_document_id: 'synthetic-document',
    printed_number: '99',
    question_type: 'single_choice',
    title: '99题 · 分苹果（合成测试题）',
    content_hash: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
  },
  script: {
    script_schema_version: '1.0.0',
    script_id: 'ts_0123456789abcdef',
    cache_key: 'synthetic-question|synthetic-revision|zh-CN|1.0.0|synthetic-v1',
    question_id: '11111111-1111-4111-8111-111111111111',
    revision_id: '22222222-2222-4222-8222-222222222222',
    revision_number: 1,
    language: 'zh-CN',
    prompt_version: 'synthetic-v1',
    model: 'synthetic',
    renderer_version: 'interactive-lesson/1.0.0',
    subject: '数学',
    source_document_id: 'synthetic-document',
    printed_number: '99',
    question_type: 'single_choice',
    title: '99题 · 分苹果（合成测试题）',
    content_hash: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
    final_answer: {
      display: 'A',
      value: 'A',
      answer_type: 'single_choice',
      grading_rule: 'exact',
      accepted_alternatives: ['A'],
      source_refs: ['ans:0'],
    },
    steps: [
      {
        step_id: 's1',
        goal: '读题：先看清已知数量，再找问题。',
        source_refs: ['cb:u99:stem:0', 'cb:u99:option:A:0', 'cb:u99:option:B:0'],
        board: [
          { id: 'b101', kind: 'heading', text: '示例：分苹果' },
          {
            id: 'b102',
            kind: 'text',
            text: '小明有 $ 3 + 2 $ 个苹果，分给小红 $ 1 $ 个。还剩几个？',
            ref: 'cb:u99:stem:0',
          },
          { id: 'b103', kind: 'choice', label: 'A', text: '$ 4 $', ref: 'cb:u99:option:A:0' },
          { id: 'b104', kind: 'choice', label: 'B', text: '$ 5 $', ref: 'cb:u99:option:B:0' },
        ],
        speech: '小明有 3 加 2 个苹果，分给小红 1 个，还剩几个？',
        subtitle: '读题时先圈出已知数量。',
        duration_ms: 3000,
        effects: [
          { at_ms: 500, type: 'show', target: 'b103' },
          { at_ms: 1000, type: 'show', target: 'b104' },
          { at_ms: 0, type: 'highlight', target: 'b102', duration_ms: 800 },
          { at_ms: 1500, type: 'pulse', target: 'b104', duration_ms: 600 },
        ],
      },
      {
        step_id: 's2',
        goal: '分析：先算总数，再减去送出的部分。',
        source_refs: ['exp:0'],
        board: [
          { id: 'b201', kind: 'callout', tone: 'info', text: '先算总数，再减去送出的部分。' },
          {
            id: 'b202',
            kind: 'table',
            rows: [
              ['步骤', '算式'],
              ['总数', '$ 3 + 2 $'],
              ['剩余', '$ 5 - 1 $'],
            ],
            ref: 'cb:u99:stem:0',
          },
          { id: 'b203', kind: 'math', latex: '5 - 1 = 4', ref: 'exp:0' },
          {
            id: 'b204',
            kind: 'image',
            asset_id: 'img_demo_placeholder',
            alt: '示意图',
            url: null,
          },
        ],
        speech: '先算总数五，再减去一，等于四。',
        subtitle: '总数 5，送出 1，剩下 4。',
        duration_ms: 3000,
        effects: [],
      },
      {
        step_id: 's3',
        goal: '结论：确认最终答案。',
        source_refs: ['ans:0'],
        board: [
          { id: 'b301', kind: 'heading', text: '结论' },
          { id: 'b302', kind: 'callout', tone: 'answer', text: '本题答案为：$ 4 $', ref: 'ans:0' },
        ],
        speech: '所以本题的答案是 A。',
        subtitle: '本题答案为 4。',
        duration_ms: 4000,
        effects: [
          { at_ms: 400, type: 'show', target: 'b302' },
          { at_ms: 0, type: 'highlight', target: 'b301', duration_ms: 600 },
        ],
      },
    ],
    sources: {
      'cb:u99:stem:0': {
        kind: 'content_block',
        question_id: '11111111-1111-4111-8111-111111111111',
        revision_id: '22222222-2222-4222-8222-222222222222',
        local_id: 'u99',
        part: 'stem',
        index: 0,
        block_kind: 'text',
        line_start: 1,
        line_end: 1,
        text: '小明有 3 + 2 个苹果，分给小红 1 个。还剩几个？',
      },
      'cb:u99:option:A:0': {
        kind: 'content_block',
        question_id: '11111111-1111-4111-8111-111111111111',
        revision_id: '22222222-2222-4222-8222-222222222222',
        local_id: 'u99',
        part: 'option',
        index: 0,
        block_kind: 'text',
        line_start: 2,
        line_end: 2,
        text: '$ 4 $',
        label: 'A',
      },
      'cb:u99:option:B:0': {
        kind: 'content_block',
        question_id: '11111111-1111-4111-8111-111111111111',
        revision_id: '22222222-2222-4222-8222-222222222222',
        local_id: 'u99',
        part: 'option',
        index: 0,
        block_kind: 'text',
        line_start: 2,
        line_end: 2,
        text: '$ 5 $',
        label: 'B',
      },
      'exp:0': {
        kind: 'explanation_block',
        question_id: '11111111-1111-4111-8111-111111111111',
        revision_id: '22222222-2222-4222-8222-222222222222',
        index: 0,
        block_kind: 'text',
        line_start: 3,
        line_end: 3,
        text: '5 - 1 = 4',
      },
      'ans:0': {
        kind: 'answer',
        question_id: '11111111-1111-4111-8111-111111111111',
        revision_id: '22222222-2222-4222-8222-222222222222',
        answer_index: 0,
        line_start: 4,
        line_end: 4,
        value_text: 'A',
      },
    },
    created_at: '2026-01-01T00:00:00+00:00',
    validation: {
      status: 'pass',
      checks: [
        { name: 'json_schema', status: 'pass', detail: 'synthetic fixture' },
        { name: 'board_targets', status: 'pass' },
        { name: 'math_renderable', status: 'pass' },
      ],
      validated_at: '2026-01-01T00:00:00+00:00',
    },
  },
  assets: [
    {
      asset_id: 'img_demo_placeholder',
      storage_path: '_imgs/demo.jpg',
      mime_type: 'image/jpeg',
    },
  ],
  answer_visibility: 'review_only',
  explanation_visibility: 'review_only',
};

export function createSyntheticBundle(): TeachingBundle {
  return structuredClone(BASE_BUNDLE);
}

/** 校验失败版本：用于断言播放器拒绝播放。 */
export function createValidationFailureBundle(): TeachingBundle {
  const bundle = createSyntheticBundle();
  bundle.script.validation.status = 'fail';
  bundle.script.validation.checks = [
    { name: 'json_schema', status: 'pass' },
    { name: 'math_renderable', status: 'fail', detail: '无法解析第 2 步公式' },
    { name: 'board_targets', status: 'fail', detail: 'effect 指向不存在的 block' },
  ];
  return bundle;
}
