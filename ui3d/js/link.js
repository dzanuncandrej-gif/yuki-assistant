/**
 * Канал к питону для пульта и звонка.
 *
 * Внутри приложения это QWebChannel. Открытая в обычном браузере страница
 * получает заглушку с теми же сигналами — так интерфейс можно отлаживать
 * без запуска Юки (заглушка лежит в window.__mock и умеет слать события).
 */

class Signal {
  constructor() { this.listeners = []; }
  connect(fn) { this.listeners.push(fn); }
  emit(...args) { this.listeners.forEach((fn) => fn(...args)); }
}

function mock(signals, slots) {
  const link = {};
  signals.forEach((name) => { link[name] = new Signal(); });
  slots.forEach((name) => { link[name] = (...args) => console.debug('[mock]', name, ...args); });
  window.__mock = link;
  return link;
}

export async function connect(signals, slots, timeout = 4000) {
  if (typeof QWebChannel === 'undefined' || !window.qt || !window.qt.webChannelTransport) {
    return mock(signals, slots);
  }
  const channel = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('канал не ответил')), timeout);
    // eslint-disable-next-line no-undef
    new QWebChannel(window.qt.webChannelTransport, (created) => { clearTimeout(timer); resolve(created); });
  });
  const link = channel.objects.yuki;
  if (!link) throw new Error('объект yuki не опубликован');
  return link;
}

/** События ядра приходят строкой JSON: так QWebChannel не теряет вложенные поля. */
export function parse(raw) {
  try { return typeof raw === 'string' ? JSON.parse(raw) : raw; } catch { return null; }
}

export const escapeHtml = (text) => String(text)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
