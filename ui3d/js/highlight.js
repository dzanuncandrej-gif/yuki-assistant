/**
 * Подсветка кода без библиотек: Python, JavaScript, CSS, HTML, JSON, Markdown.
 *
 * Один проход слева направо по строке комбинированным выражением: строка или
 * комментарий съедают свой текст целиком, поэтому «#» внутри строки "#1e1e2e"
 * не превращает остаток в комментарий. Многострочные строки и комментарии
 * держатся состоянием между строками.
 */

import { escapeHtml } from './link.js';

const KEYWORDS = {
  python: 'and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case',
  js: 'async await break case catch class const continue debugger default delete do else export extends finally for from function if import in instanceof let new of return static super switch this throw try typeof var void while yield',
};
const CONSTANTS = 'True False None self cls true false null undefined NaN Infinity this';
const BUILTINS = 'print len range int str float list dict set tuple open enumerate zip map filter sorted min max sum abs round isinstance super console document window Math JSON Array Object String Number Date localStorage setTimeout setInterval requestAnimationFrame';

const words = (text) => new Set(text.split(' '));
const KW = { python: words(KEYWORDS.python), js: words(KEYWORDS.js) };
const CONST = words(CONSTANTS);
const BUILT = words(BUILTINS);

export function languageOf(path = '') {
  const ext = path.split('.').pop().toLowerCase();
  return { py: 'python', js: 'js', mjs: 'js', css: 'css', html: 'html', htm: 'html', json: 'js', md: 'md' }[ext] || 'text';
}

const span = (cls, text) => `<span class="t-${cls}">${escapeHtml(text)}</span>`;

function codeLine(line, lang, state) {
  let out = '';
  let rest = line;
  // продолжение многострочной строки/комментария с прошлой строки
  if (state.open) {
    const end = rest.indexOf(state.open);
    if (end < 0) return span(state.cls, rest);
    out += span(state.cls, rest.slice(0, end + state.open.length));
    rest = rest.slice(end + state.open.length);
    state.open = null;
  }
  const comment = lang === 'python' ? '#[^\\n]*' : lang === 'css' ? '' : '\\/\\/[^\\n]*';
  const token = new RegExp(
    [
      lang === 'python' ? '(?<triple>"""|\'\'\')' : '',
      lang !== 'python' ? '(?<block>\\/\\*)' : '',
      '(?<str>[rbfRBF]{0,2}(?<q>["\'`])(?:\\\\.|(?!\\k<q>).)*\\k<q>)',
      comment ? `(?<com>${comment})` : '',
      lang === 'python' ? '(?<deco>@[\\w.]+)' : '',
      '(?<num>\\b\\d+(?:\\.\\d+)?\\b|#[0-9a-fA-F]{3,8}\\b)',
      lang === 'css' ? '(?<prop>[\\w-]+)(?=\\s*:)' : '',
      '(?<word>[A-Za-z_$][\\w$]*)',
    ].filter(Boolean).join('|'),
    'g',
  );
  let last = 0;
  let previous = '';
  // exec, а не matchAll: после тройной кавычки поиск продолжается за её концом
  for (let match = token.exec(rest); match; match = token.exec(rest)) {
    if (match[0] === '') { token.lastIndex += 1; continue; }
    out += escapeHtml(rest.slice(last, match.index));
    last = match.index + match[0].length;
    const g = match.groups;
    if (g.triple || g.block) {
      const close = g.triple || '*/';
      const end = rest.indexOf(close, last);
      if (end < 0) {
        state.open = close; state.cls = g.triple ? 'str' : 'com';
        out += span(state.cls, rest.slice(match.index));
        return out;
      }
      out += span(g.triple ? 'str' : 'com', rest.slice(match.index, end + close.length));
      last = end + close.length;
      token.lastIndex = last;
    } else if (g.str) out += span('str', g.str);
    else if (g.com) out += span('com', g.com);
    else if (g.deco) out += span('deco', g.deco);
    else if (g.num) out += span('num', g.num);
    else if (g.prop) out += span('prop', g.prop);
    else if (g.word) {
      const word = g.word;
      const kws = KW[lang] || KW.js;
      if (previous === 'def' || previous === 'class' || previous === 'function') out += span('fn', word);
      else if (lang !== 'css' && kws.has(word)) out += span('kw', word);
      else if (CONST.has(word)) out += span('const', word);
      else if (BUILT.has(word)) out += span('built', word);
      else if (/^[A-Z][A-Z0-9_]{2,}$/.test(word)) out += span('const', word);
      else if (rest[last] === '(') out += span('call', word);
      else out += escapeHtml(word);
      previous = word;
      continue;
    }
    previous = '';
  }
  return out + escapeHtml(rest.slice(last));
}

function htmlLine(line, state) {
  if (state.open) {
    const end = line.indexOf('-->');
    if (end < 0) return span('com', line);
    state.open = null;
    return span('com', line.slice(0, end + 3)) + htmlLine(line.slice(end + 3), state);
  }
  let out = '';
  let last = 0;
  const token = /<!--[\s\S]*?(?:-->|$)|<\/?([\w-]+)|([\w-:@]+)(?==)|("[^"]*"|'[^']*')|\/?>/g;
  for (const match of line.matchAll(token)) {
    out += escapeHtml(line.slice(last, match.index));
    last = match.index + match[0].length;
    if (match[0].startsWith('<!--')) {
      if (!match[0].endsWith('-->')) state.open = '-->';
      out += span('com', match[0]);
    } else if (match[1]) out += span('punc', match[0].slice(0, match[0].length - match[1].length)) + span('tag', match[1]);
    else if (match[2]) out += span('attr', match[2]);
    else if (match[3]) out += span('str', match[3]);
    else out += span('punc', match[0]);
  }
  return out + escapeHtml(line.slice(last));
}

/** Массив HTML-строк — по одной на строку кода. */
export function highlight(code, lang) {
  const state = { open: null, cls: 'str' };
  return String(code).split('\n').map((line) => {
    if (lang === 'html') return htmlLine(line, state);
    if (lang === 'md' || lang === 'text') return escapeHtml(line);
    return codeLine(line, lang, state);
  });
}
