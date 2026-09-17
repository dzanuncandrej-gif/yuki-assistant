/**
 * Связь со стороной Qt.
 *
 * Приложение остаётся десктопным: страница живёт внутри виджета QWebEngineView,
 * а разговор с питоном идёт по QWebChannel — без сети, портов и браузера.
 * Если канала нет (открыли страницу в обычном браузере для отладки), подставляем
 * заглушку, чтобы сцена всё равно поднялась.
 */

const NOOP = () => {};

class Signal {
  constructor() { this._listeners = []; }
  connect(fn) { this._listeners.push(fn); }
  emit(...args) { for (const fn of this._listeners) fn(...args); }
}

/** Заглушка на время отладки в браузере: те же сигналы, только их никто не шлёт. */
function mockLink() {
  const link = {
    stateChanged: new Signal(),
    levelChanged: new Signal(),
    visemeChanged: new Signal(),
    emotionRequested: new Signal(),
    gestureRequested: new Signal(),
    reactRequested: new Signal(),
    settingsChanged: new Signal(),
    characterChanged: new Signal(),
    pointerMoved: new Signal(),
    onReady: NOOP,
    onClick: NOOP,
    onDragStart: NOOP,
    onError: (text) => console.error('[avatar]', text),
  };
  window.__mockLink = link;
  return link;
}

export async function connect(timeout = 4000) {
  if (typeof QWebChannel === 'undefined' || !window.qt || !window.qt.webChannelTransport) {
    return mockLink();
  }
  const channel = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('канал не ответил')), timeout);
    // eslint-disable-next-line no-undef
    new QWebChannel(window.qt.webChannelTransport, (created) => {
      clearTimeout(timer);
      resolve(created);
    });
  });
  const link = channel.objects.jarvis;
  if (!link) throw new Error('объект jarvis не опубликован');
  return link;
}
