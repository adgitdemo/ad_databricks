import { describe, it, expect, afterEach } from 'vitest';
import { parseSummaryDetails, wrapQuestion, genieConversationUrl } from './genie';

describe('parseSummaryDetails', () => {
  it('splits a well-formed SUMMARY / DETAILS response', () => {
    const { summary, details } = parseSummaryDetails(
      'SUMMARY: Sales are up sharply this quarter.\nDETAILS: Q3 revenue was $1.2M, up 40%.',
    );
    expect(summary).toBe('Sales are up sharply this quarter.');
    expect(details).toBe('Q3 revenue was $1.2M, up 40%.');
  });

  it('tolerates markdown emphasis and backticks around the labels', () => {
    const { summary, details } = parseSummaryDetails(
      '**SUMMARY:** Revenue grew.\n\n`DETAILS:` Exact figures follow.',
    );
    expect(summary).toBe('Revenue grew.');
    expect(details).toBe('Exact figures follow.');
  });

  it('falls back to narrating the whole answer when labels are missing', () => {
    const text = 'Just a plain answer with no sections.';
    expect(parseSummaryDetails(text)).toEqual({ summary: text, details: '' });
  });

  it('falls back when DETAILS appears before SUMMARY', () => {
    const text = 'DETAILS: figures first.\nSUMMARY: spoken part.';
    const { summary, details } = parseSummaryDetails(text);
    expect(summary).toBe(text.trim());
    expect(details).toBe('');
  });

  it('falls back when the summary section is empty', () => {
    const text = 'SUMMARY:\nDETAILS: only details here.';
    const { summary } = parseSummaryDetails(text);
    expect(summary).toBe(text.trim());
  });
});

describe('wrapQuestion', () => {
  it('embeds the question and asks for both sections', () => {
    const wrapped = wrapQuestion('How did sales do?');
    expect(wrapped).toContain('Question: How did sales do?');
    expect(wrapped).toContain('SUMMARY:');
    expect(wrapped).toContain('DETAILS:');
  });
});

describe('genieConversationUrl', () => {
  const KEY = 'DATABRICKS_WORKSPACE_ID';
  const original = process.env[KEY];
  afterEach(() => {
    if (original === undefined) delete process.env[KEY];
    else process.env[KEY] = original;
  });

  it('builds the rooms/chats path and prepends https:// to a bare host', () => {
    delete process.env[KEY];
    const url = genieConversationUrl('example.cloud.databricks.com', 'space123', 'conv456');
    expect(url).toBe('https://example.cloud.databricks.com/genie/rooms/space123/chats/conv456');
  });

  it('keeps an existing scheme and appends the workspace id when set', () => {
    process.env[KEY] = '42';
    const url = genieConversationUrl('https://example.cloud.databricks.com', 'space123', 'conv456');
    expect(url).toBe(
      'https://example.cloud.databricks.com/genie/rooms/space123/chats/conv456?o=42',
    );
  });
});
