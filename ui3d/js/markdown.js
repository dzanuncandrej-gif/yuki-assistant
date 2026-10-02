/**
 * Маленький безопасный markdown для развёрнутых ответов.
 *
 * Текст сначала экранируется целиком, и только потом в него добавляется
 * разметка — поэтому ответ модели не может вставить в страницу свой HTML.
 * Поддержано то, что модель реально пишет: заголовки, списки, жирный,
 * курсив, код строкой и блоком, цитаты, разделители, таблицы.
 */
import { escapeHtml } from './link.js';

function inline(text) {
  return text
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/(^|\s)_([^_\n]+)_(?=\s|$|[.,!?])/g, '$1<em>$2</em>');
}

function table(rows) {
  const cells = (row) => row.replace(/^\||\|$/g, '').split('|').map((c) => inline(c.trim()));
  const [head, , ...body] = rows;
  return `<div class="md-table"><table><thead><tr>${cells(head).map((c) => `<th>${c}</th>`).join('')}</tr></thead>`
    + `<tbody>${body.map((r) => `<tr>${cells(r).map((c) => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

export function render(source) {
  const lines = escapeHtml(source.replace(/\r/g, '')).split('\n');
  const out = [];
  let list = null;
  let para = [];
  const flushPara = () => { if (para.length) { out.push(`<p>${inline(para.join(' '))}</p>`); para = []; } };
  const flushList = () => { if (list) { out.push(`</${list}>`); list = null; } };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const fence = line.match(/^```\s*([\w+-]*)/);
    if (fence) {
      flushPara(); flushList();
      const code = [];
      for (i += 1; i < lines.length && !/^```/.test(lines[i]); i++) code.push(lines[i]);
      out.push(`<div class="md-code"><div class="md-code__bar"><span>${fence[1] || 'код'}</span><button type="button" data-copy>копировать</button></div><pre><code>${code.join('\n')}</code></pre></div>`);
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1] || '')) {
      flushPara(); flushList();
      const rows = [];
      for (; i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i]); i++) rows.push(lines[i].trim());
      i -= 1;
      out.push(table(rows));
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) { flushPara(); flushList(); const n = Math.min(4, heading[1].length + 1); out.push(`<h${n}>${inline(heading[2])}</h${n}>`); continue; }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { flushPara(); flushList(); out.push('<hr>'); continue; }
    const quote = line.match(/^&gt;\s?(.*)$/);
    if (quote) { flushPara(); flushList(); out.push(`<blockquote>${inline(quote[1])}</blockquote>`); continue; }
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (bullet || numbered) {
      flushPara();
      const kind = bullet ? 'ul' : 'ol';
      if (list !== kind) { flushList(); out.push(`<${kind}>`); list = kind; }
      out.push(`<li>${inline((bullet || numbered)[1])}</li>`);
      continue;
    }
    if (!line.trim()) { flushPara(); flushList(); continue; }
    flushList();
    para.push(line.trim());
  }
  flushPara(); flushList();
  return out.join('');
}

/** Кнопки «копировать» у блоков кода. Вешается один раз на контейнер. */
export function wireCopy(root, copy) {
  root.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-copy]');
    if (!btn) return;
    const code = btn.closest('.md-code')?.querySelector('code')?.textContent || '';
    copy(code);
    btn.textContent = 'скопировано';
    setTimeout(() => { btn.textContent = 'копировать'; }, 1600);
  });
}
