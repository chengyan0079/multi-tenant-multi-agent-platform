/** 配置内容格式校验：返回可展示的错误行号，供 CodeEditor / Antd Form 共用。 */
export type CodeLanguage = 'text' | 'json' | 'yaml' | 'xml' | 'properties' | 'html';

export interface CodeValidationError {
  line: number;
  column?: number;
  message: string;
}

const LANGUAGES: CodeLanguage[] = ['text', 'json', 'yaml', 'xml', 'properties', 'html'];

export function normalizeCodeLanguage(value?: string | null): CodeLanguage {
  const lang = (value ?? '').toLowerCase();
  return (LANGUAGES as string[]).includes(lang) ? (lang as CodeLanguage) : 'text';
}

function lineColumnAt(text: string, offset: number): { line: number; column: number } {
  const safe = Math.max(0, Math.min(offset, text.length));
  const before = text.slice(0, safe);
  const line = before.split('\n').length;
  const lastBreak = before.lastIndexOf('\n');
  return { line, column: safe - lastBreak };
}

function addError(
  errors: CodeValidationError[],
  line: number,
  message: string,
  column?: number,
): void {
  errors.push({ line: Math.max(1, line), column, message });
}

function maskStrings(text: string, quote: '"' | "'" = '"'): string {
  const pattern = quote === '"'
    ? /"(?:\\.|[^"\\])*"?/g
    : /'(?:''|[^'])*'?/g;
  return text.replace(pattern, (match) => match[0] + ' '.repeat(Math.max(0, match.length - 1)));
}

function maskComments(text: string): string {
  return text.replace(/#[^\n]*/g, (match) => ' '.repeat(match.length));
}

function validateJson(text: string): CodeValidationError[] {
  const errors: CodeValidationError[] = [];
  const masked = maskStrings(text);

  const comment = /\/\/[^\n]*|\/\*[\s\S]*?\*\//g;
  for (const found of masked.matchAll(comment)) {
    const { line, column } = lineColumnAt(text, found.index ?? 0);
    addError(errors, line, 'JSON 不支持注释', column);
  }

  const trailingComma = /,\s*([}\]])/g;
  for (const found of masked.matchAll(trailingComma)) {
    const { line, column } = lineColumnAt(text, (found.index ?? 0) + found[0].indexOf(','));
    addError(errors, line, '对象或数组最后一个元素后不能有逗号', column);
  }

  try {
    JSON.parse(text);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const lineMatch = /line\s+(\d+)\s+column\s+(\d+)/i.exec(message);
    const posMatch = /position\s+(\d+)/i.exec(message);
    let line = text.split('\n').length;
    let column: number | undefined;
    if (lineMatch) {
      line = Number(lineMatch[1]);
      column = Number(lineMatch[2]);
    } else if (posMatch) {
      const at = lineColumnAt(text, Number(posMatch[1]));
      line = at.line;
      column = at.column;
    }
    addError(errors, line, `JSON 解析失败：${message}`, column);
  }
  return errors;
}

function stripYamlComment(line: string): string {
  let single = false;
  let double = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (char === "'" && !double) {
      if (single && line[i + 1] === "'") {
        i += 1;
        continue;
      }
      single = !single;
    } else if (char === '"' && !single && line[i - 1] !== '\\') {
      double = !double;
    } else if (char === '#' && !single && !double && (i === 0 || /\s/.test(line[i - 1]))) {
      return line.slice(0, i);
    }
  }
  return line;
}

function hasUnclosedQuote(line: string): boolean {
  let single = false;
  let double = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (char === "'" && !double) {
      if (single && line[i + 1] === "'") {
        i += 1;
        continue;
      }
      single = !single;
    } else if (char === '"' && !single && line[i - 1] !== '\\') {
      double = !double;
    }
  }
  return single || double;
}

function validateBrackets(text: string, errors: CodeValidationError[]): void {
  const masked = maskComments(maskStrings(maskStrings(text, "'")));
  const stack: { char: string; line: number; column: number }[] = [];
  const pairs: Record<string, string> = { ']': '[', '}': '{' };
  let line = 1;
  for (let i = 0; i < masked.length; i += 1) {
    const char = masked[i];
    if (char === '\n') {
      line += 1;
      continue;
    }
    if (char === '[' || char === '{') {
      stack.push({ char, line, column: i - masked.lastIndexOf('\n', i - 1) });
    } else if (char === ']' || char === '}') {
      const top = stack.pop();
      if (!top || top.char !== pairs[char]) {
        addError(errors, line, `多余的 ${char}，没有对应的 ${pairs[char]}`);
      }
    }
  }
  for (const item of stack) {
    addError(errors, item.line, `${item.char} 未闭合`, item.column);
  }
}

function validateYaml(text: string): CodeValidationError[] {
  const errors: CodeValidationError[] = [];
  const lines = text.split('\n');
  let blockScalarIndent: number | null = null;

  lines.forEach((raw, index) => {
    const lineNo = index + 1;
    if (/^\s*\t/.test(raw)) {
      addError(errors, lineNo, 'YAML 缩进不能使用 Tab');
    }

    const indent = raw.match(/^ */)?.[0].length ?? 0;
    if (blockScalarIndent !== null) {
      if (raw.trim() === '' || indent > blockScalarIndent) return;
      blockScalarIndent = null;
    }

    const code = stripYamlComment(raw).trimEnd();
    if (!code.trim() || /^(---|\.\.\.)\s*$/.test(code.trim())) return;
    if (hasUnclosedQuote(code)) {
      addError(errors, lineNo, '字符串引号未闭合');
      return;
    }
    if (/:\s*[|>][+-]?\d*\s*$/.test(code)) {
      blockScalarIndent = indent;
      return;
    }
    if (/^\s*-\s*(.*)$/.test(code)) return;
    if (/^\s*(?:[A-Za-z_][\w.-]*|"[^"]*"|'[^']*')\s*:/.test(code)) return;
    if (indent === 0 && /^[^{}[\],#:]+$/.test(code.trim())) return;

    addError(errors, lineNo, '不是合法的 YAML 映射/列表项（期望 key: value 或 - item）');
  });

  validateBrackets(text, errors);
  return errors;
}

const HTML_VOID_TAGS = new Set([
  'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
  'link', 'meta', 'param', 'source', 'track', 'wbr',
]);

function validateMarkup(text: string, language: 'xml' | 'html'): CodeValidationError[] {
  const errors: CodeValidationError[] = [];
  const stack: { name: string; line: number }[] = [];
  const pattern = /<!--[\s\S]*?-->|<!DOCTYPE[^>]*>|<!doctype[^>]*>|<\?[\s\S]*?\?>|<\/?([A-Za-z][\w:-]*)([^>]*)>/g;
  const normalize = (name: string) => (language === 'html' ? name.toLowerCase() : name);

  for (const found of text.matchAll(pattern)) {
    const full = found[0];
    if (full.startsWith('<!--') || /^<!DOCTYPE|^<!doctype|^\<\?/i.test(full)) continue;

    const { line } = lineColumnAt(text, found.index ?? 0);
    const name = normalize(found[1]);
    const attrs = found[2] ?? '';
    const doubleQuotes = (attrs.match(/"/g) ?? []).length;
    const singleQuotes = (attrs.match(/'/g) ?? []).length;
    if (doubleQuotes % 2 !== 0 || singleQuotes % 2 !== 0) {
      addError(errors, line, `<${name}> 属性引号未闭合`);
    }

    const isClosing = /^<\//.test(full);
    const isSelfClosing = /\/\s*>$/.test(full) || (language === 'html' && HTML_VOID_TAGS.has(name));
    if (isClosing) {
      const top = stack[stack.length - 1];
      if (!top) {
        addError(errors, line, `多余的结束标签 </${name}>`);
      } else if (top.name !== name) {
        addError(errors, line, `结束标签 </${name}> 与第 ${top.line} 行的 <${top.name}> 不匹配`);
        const matchedIndex = stack.map((item) => item.name).lastIndexOf(name);
        stack.length = matchedIndex >= 0 ? matchedIndex : stack.length - 1;
      } else {
        stack.pop();
      }
    } else if (!isSelfClosing) {
      stack.push({ name, line });
    }
  }

  const openComment = text.indexOf('<!--');
  if (openComment >= 0 && text.indexOf('-->', openComment + 4) < 0) {
    addError(errors, lineColumnAt(text, openComment).line, '注释 <!-- 未闭合');
  }
  for (const item of stack) {
    addError(errors, item.line, `<${item.name}> 未闭合`);
  }
  return errors;
}

function endsWithContinuation(line: string): boolean {
  let count = 0;
  for (let i = line.length - 1; i >= 0 && line[i] === '\\'; i -= 1) count += 1;
  return count % 2 === 1;
}

function validateProperties(text: string): CodeValidationError[] {
  const errors: CodeValidationError[] = [];
  const seen = new Set<string>();
  let continuation = false;

  text.split('\n').forEach((raw, index) => {
    const lineNo = index + 1;
    if (continuation) {
      continuation = endsWithContinuation(raw.trimEnd());
      return;
    }
    const trimmed = raw.trim();
    if (!trimmed || /^[#!]/.test(trimmed)) return;
    if (/^[=:]/.test(trimmed)) {
      addError(errors, lineNo, '缺少属性名（行首就是分隔符）');
      return;
    }
    if (/\\u(?![0-9a-fA-F]{4})/.test(raw)) {
      addError(errors, lineNo, '\\u 转义必须跟 4 位十六进制字符');
    }

    const keyMatch = /^\s*((?:\\.|[^=:\s])+)\s*(?:[=:]|\s|$)/.exec(raw);
    const key = (keyMatch?.[1] ?? trimmed).replace(/\\(.)/g, '$1');
    if (seen.has(key)) {
      addError(errors, lineNo, `重复的属性名：${key}`);
    } else {
      seen.add(key);
    }
    continuation = endsWithContinuation(raw.trimEnd());
  });

  if (continuation) {
    addError(errors, text.split('\n').length, '行尾续行符 \\ 后缺少下一行');
  }
  return errors;
}

/** 按格式校验内容；返回最多 20 条带行号的错误。text 不做语法校验。 */
export function validateCode(
  language: string | undefined,
  value: string,
): CodeValidationError[] {
  const lang = normalizeCodeLanguage(language);
  if (!value || !value.trim()) return [];
  let errors: CodeValidationError[] = [];
  switch (lang) {
    case 'json':
      errors = validateJson(value);
      break;
    case 'yaml':
      errors = validateYaml(value);
      break;
    case 'xml':
    case 'html':
      errors = validateMarkup(value, lang);
      break;
    case 'properties':
      errors = validateProperties(value);
      break;
    default:
      errors = [];
  }
  return errors.slice(0, 20);
}
