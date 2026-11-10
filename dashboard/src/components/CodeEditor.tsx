import { useEffect, useMemo, useRef } from 'react';
import type { KeyboardEvent, ReactElement, UIEvent } from 'react';

import {
  normalizeCodeLanguage,
  validateCode,
  type CodeLanguage,
  type CodeValidationError,
} from './codeValidation';

export { normalizeCodeLanguage, validateCode } from './codeValidation';
export type { CodeLanguage, CodeValidationError } from './codeValidation';

type TokenType =
  | 'plain'
  | 'comment'
  | 'key'
  | 'string'
  | 'number'
  | 'boolean'
  | 'null'
  | 'punct'
  | 'tag'
  | 'attr'
  | 'value';

type Token = { type: TokenType; text: string };
type Rule = { type: TokenType; re: RegExp };
type PreRef = { current: HTMLPreElement | null };

const PLACEHOLDERS: Record<CodeLanguage, string> = {
  text: '粘贴完整配置内容',
  json: '{\n  "key": "value"\n}',
  yaml: 'server:\n  port: 8080\nenabled: true',
  xml: '<?xml version="1.0" encoding="UTF-8"?>\n<root>\n  <item key="value" />\n</root>',
  properties: '# 注释\nkey=value\nanother.key: value',
  html: '<!doctype html>\n<html>\n  <body>hello</body>\n</html>',
};

function rulesFor(language: CodeLanguage): Rule[] {
  switch (language) {
    case 'json':
      return [
        { type: 'comment', re: /\/\/.*/y },
        { type: 'key', re: /"(?:\\.|[^"\\])*"(?=\s*:)/y },
        { type: 'string', re: /"(?:\\.|[^"\\])*"?/y },
        { type: 'number', re: /-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/y },
        { type: 'boolean', re: /\b(?:true|false)\b/y },
        { type: 'null', re: /\bnull\b/y },
        { type: 'punct', re: /[{}\[\],:]/y },
      ];
    case 'yaml':
      return [
        { type: 'comment', re: /#.*/y },
        { type: 'key', re: /[A-Za-z_][\w.-]*(?=\s*:)/y },
        { type: 'string', re: /"(?:\\.|[^"\\])*"?|'(?:''|[^'])*'?/y },
        { type: 'boolean', re: /\b(?:true|false|yes|no|on|off|True|False|Yes|No)\b/y },
        { type: 'null', re: /\b(?:null|Null|NULL|~)\b/y },
        { type: 'number', re: /-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/y },
        { type: 'tag', re: /[&*][A-Za-z0-9_-]+|!!?[\w:/.-]+/y },
        { type: 'punct', re: /[-:|>]/y },
      ];
    case 'xml':
    case 'html':
      return [
        { type: 'comment', re: /<!--.*?-->|<!--.*/y },
        { type: 'tag', re: /<!DOCTYPE[^>]*>|<!doctype[^>]*>|<\?.*?\?>|<\/?[A-Za-z][\w:-]*/iy },
        { type: 'attr', re: /[A-Za-z_:][\w:.-]*(?=\s*=)/y },
        { type: 'string', re: /"(?:\\.|[^"\\])*"?|'(?:\\.|[^'\\])*'?/y },
        { type: 'punct', re: /\/?>|[=/]/y },
      ];
    case 'properties':
      return [
        { type: 'comment', re: /[#!].*/y },
        { type: 'key', re: /[^:=\s]+(?=\s*[=:])/y },
        { type: 'punct', re: /[=:]/y },
        { type: 'string', re: /\\u[0-9a-fA-F]{4}/y },
        { type: 'value', re: /[^\r\n]+/y },
      ];
    default:
      return [];
  }
}

function tokenizeLine(line: string, rules: Rule[]): Token[] {
  if (!rules.length || !line) return [{ type: 'plain', text: line }];
  const tokens: Token[] = [];
  let pos = 0;
  let plain = '';

  const flush = () => {
    if (plain) {
      tokens.push({ type: 'plain', text: plain });
      plain = '';
    }
  };

  while (pos < line.length) {
    let matched: Token | null = null;
    for (const rule of rules) {
      rule.re.lastIndex = pos;
      const found = rule.re.exec(line);
      if (found && found.index === pos && found[0].length > 0) {
        matched = { type: rule.type, text: found[0] };
        break;
      }
    }
    if (matched) {
      flush();
      tokens.push(matched);
      pos += matched.text.length;
    } else {
      plain += line[pos];
      pos += 1;
    }
  }
  flush();
  return tokens.length ? tokens : [{ type: 'plain', text: '' }];
}

function renderTokens(tokens: Token[]): ReactElement[] {
  return tokens.map((token, index) => (
    <span className={`code-editor__token code-editor__token--${token.type}`} key={index}>
      {token.text}
    </span>
  ));
}

/** 给 ReactDiffViewer.renderContent 使用：按格式渲染单行/片段。 */
export function renderCodeLine(source: string, language?: string): ReactElement {
  const tokens = tokenizeLine(source, rulesFor(normalizeCodeLanguage(language)));
  return <span className="code-editor__inline-highlight">{renderTokens(tokens)}</span>;
}

interface CodeHighlightProps {
  lines: string[];
  rules: Rule[];
  errorLines: Set<number>;
  preRef?: PreRef;
  onScroll?: (event: UIEvent<HTMLPreElement>) => void;
  interactive?: boolean;
  ariaLabel?: string;
}

function CodeHighlight({
  lines,
  rules,
  errorLines,
  preRef,
  onScroll,
  interactive = false,
  ariaLabel,
}: CodeHighlightProps) {
  return (
    <pre
      className={`code-editor__highlight${interactive ? ' code-editor__highlight--interactive' : ''}`}
      ref={preRef}
      onScroll={onScroll}
      aria-hidden={!interactive}
      aria-label={interactive ? ariaLabel : undefined}
    >
      <code>
        {lines.map((line, lineIndex) => (
          <span
            className={`code-editor__code-line${errorLines.has(lineIndex + 1) ? ' is-error' : ''}`}
            key={lineIndex}
          >
            {renderTokens(tokenizeLine(line, rules))}
            {line ? null : '\u200b'}
            {lineIndex < lines.length - 1 ? '\n' : null}
          </span>
        ))}
      </code>
    </pre>
  );
}

function ErrorList({ errors }: { errors: CodeValidationError[] }) {
  if (!errors.length) return null;
  return (
    <div className="code-editor__errors" role="alert">
      <div className="code-editor__errors-title">
        发现 {errors.length} 处格式问题，错误行号已标红：
      </div>
      {errors.slice(0, 5).map((error, index) => (
        <div className="code-editor__error" key={`${error.line}-${index}`}>
          <span className="code-editor__error-line">第 {error.line} 行</span>
          <span>{error.message}</span>
        </div>
      ))}
      {errors.length > 5 ? (
        <div className="code-editor__error-more">还有 {errors.length - 5} 处错误…</div>
      ) : null}
    </div>
  );
}

export interface CodeEditorProps {
  value?: string;
  onChange?: (value: string) => void;
  onBlur?: () => void;
  onValidate?: (errors: CodeValidationError[]) => void;
  language?: string;
  rows?: number;
  placeholder?: string;
  readOnly?: boolean;
  showValidation?: boolean;
  ariaLabel?: string;
}

/** 轻量代码编辑器：透明 textarea 负责输入，pre 负责按格式高亮，二者滚动同步。 */
export default function CodeEditor({
  value,
  onChange,
  onBlur,
  onValidate,
  language,
  rows = 8,
  placeholder,
  readOnly = false,
  showValidation = true,
  ariaLabel = '配置内容代码编辑器',
}: CodeEditorProps) {
  const highlightRef = useRef<HTMLPreElement | null>(null);
  const gutterRef = useRef<HTMLDivElement | null>(null);
  const lang = normalizeCodeLanguage(language);
  const content = value ?? '';
  const lines = useMemo(() => content.split('\n'), [content]);
  const rules = useMemo(() => rulesFor(lang), [lang]);
  const errors = useMemo(
    () => (showValidation ? validateCode(lang, content) : []),
    [showValidation, lang, content],
  );
  const errorLines = useMemo(
    () => new Set(
      errors.map((error) => Math.min(Math.max(1, error.line), Math.max(1, lines.length))),
    ),
    [errors, lines.length],
  );
  const errorsByLine = useMemo(() => {
    const grouped = new Map<number, CodeValidationError[]>();
    for (const error of errors) {
      const line = Math.min(Math.max(1, error.line), Math.max(1, lines.length));
      grouped.set(line, [...(grouped.get(line) ?? []), error]);
    }
    return grouped;
  }, [errors, lines.length]);
  const bodyHeight = Math.max(4, rows) * 22 + 24;

  useEffect(() => {
    if (showValidation) onValidate?.(errors);
  }, [errors, onValidate, showValidation]);

  const syncScroll = (event: UIEvent<HTMLTextAreaElement>) => {
    const { scrollTop, scrollLeft } = event.currentTarget;
    if (highlightRef.current) {
      highlightRef.current.scrollTop = scrollTop;
      highlightRef.current.scrollLeft = scrollLeft;
    }
    if (gutterRef.current) {
      gutterRef.current.scrollTop = scrollTop;
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Tab' || readOnly) return;
    event.preventDefault();
    const target = event.currentTarget;
    const start = target.selectionStart;
    const end = target.selectionEnd;
    const next = `${content.slice(0, start)}  ${content.slice(end)}`;
    onChange?.(next);
    requestAnimationFrame(() => {
      target.selectionStart = start + 2;
      target.selectionEnd = start + 2;
    });
  };

  return (
    <div className="code-editor">
      <div className="code-editor__header">
        <span className="code-editor__lang">{lang.toUpperCase()}</span>
        <span className="code-editor__hint">
          {lines.length} 行 · Tab 插入 2 空格 · 按 {lang.toUpperCase()} 高亮
        </span>
        {showValidation ? (
          <span className={`code-editor__status${errors.length ? ' is-error' : ' is-ok'}`}>
            {errors.length ? `${errors.length} 处错误` : content.trim() ? '格式检查通过' : '等待输入'}
          </span>
        ) : null}
      </div>
      <div className="code-editor__body" style={{ height: bodyHeight }}>
        <div className="code-editor__gutter" ref={gutterRef} aria-hidden>
          {lines.map((_, index) => {
            const lineNo = index + 1;
            const lineErrors = errorsByLine.get(lineNo) ?? [];
            return (
              <div
                className={`code-editor__gutter-line${lineErrors.length ? ' is-error' : ''}`}
                key={lineNo}
                title={lineErrors.map((item) => item.message).join('；') || undefined}
              >
                {lineNo}
              </div>
            );
          })}
        </div>
        <div className="code-editor__area">
          <CodeHighlight
            lines={lines}
            rules={rules}
            errorLines={errorLines}
            preRef={highlightRef}
          />
          <textarea
            className="code-editor__textarea"
            value={content}
            onChange={(event) => onChange?.(event.target.value)}
            onBlur={onBlur}
            onScroll={syncScroll}
            onKeyDown={handleKeyDown}
            placeholder={placeholder ?? PLACEHOLDERS[lang]}
            spellCheck={false}
            readOnly={readOnly}
            aria-label={ariaLabel}
          />
        </div>
      </div>
      {showValidation ? <ErrorList errors={errors} /> : null}
    </div>
  );
}

export interface CodeViewerProps {
  value?: string;
  language?: string;
  rows?: number;
  showValidation?: boolean;
  ariaLabel?: string;
}

/** 只读代码查看器：配置详情/历史版本按格式高亮，不渲染输入框。 */
export function CodeViewer({
  value,
  language,
  rows = 12,
  showValidation = false,
  ariaLabel = '配置内容代码查看器',
}: CodeViewerProps) {
  const highlightRef = useRef<HTMLPreElement | null>(null);
  const gutterRef = useRef<HTMLDivElement | null>(null);
  const lang = normalizeCodeLanguage(language);
  const content = value ?? '';
  const lines = useMemo(() => content.split('\n'), [content]);
  const rules = useMemo(() => rulesFor(lang), [lang]);
  const errors = useMemo(
    () => (showValidation ? validateCode(lang, content) : []),
    [showValidation, lang, content],
  );
  const errorLines = useMemo(
    () => new Set(
      errors.map((error) => Math.min(Math.max(1, error.line), Math.max(1, lines.length))),
    ),
    [errors, lines.length],
  );
  const bodyHeight = Math.max(4, rows) * 22 + 24;

  const syncScroll = (event: UIEvent<HTMLPreElement>) => {
    if (gutterRef.current) gutterRef.current.scrollTop = event.currentTarget.scrollTop;
  };

  return (
    <div className="code-editor code-editor--viewer">
      <div className="code-editor__header">
        <span className="code-editor__lang">{lang.toUpperCase()}</span>
        <span className="code-editor__hint">只读 · {lines.length} 行 · 按 {lang.toUpperCase()} 高亮</span>
        {showValidation ? (
          <span className={`code-editor__status${errors.length ? ' is-error' : ' is-ok'}`}>
            {errors.length ? `${errors.length} 处错误` : content.trim() ? '格式检查通过' : '等待输入'}
          </span>
        ) : null}
      </div>
      <div className="code-editor__body" style={{ height: bodyHeight }}>
        <div className="code-editor__gutter" ref={gutterRef} aria-hidden>
          {lines.map((_, index) => (
            <div
              className={`code-editor__gutter-line${errorLines.has(index + 1) ? ' is-error' : ''}`}
              key={index + 1}
            >
              {index + 1}
            </div>
          ))}
        </div>
        <div className="code-editor__area">
          <CodeHighlight
            lines={lines}
            rules={rules}
            errorLines={errorLines}
            preRef={highlightRef}
            onScroll={syncScroll}
            interactive
            ariaLabel={ariaLabel}
          />
        </div>
      </div>
      {showValidation ? <ErrorList errors={errors} /> : null}
    </div>
  );
}
