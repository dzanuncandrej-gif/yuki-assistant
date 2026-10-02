"""Робот-тестировщик для сайтов: скрытый Chromium из Qt нажимает всё на странице.

Запускается отдельным процессом на Python самой Юки (там есть QtWebEngine),
поэтому работает у любого пользователя без Node и браузерных драйверов.
Печатает строку `WEBROBOT clicked=N errors=M` и сами ошибки JavaScript.

    python -m core.coding.webrobot путь/к/index.html
"""

from __future__ import annotations

import json
import sys

# Qt не умеет ждать промисы из runJavaScript, поэтому нажатия синхронные,
# а ошибки забираются отдельным вызовом, когда таймеры страницы отработают.
CLICK_ALL = r"""
(() => {
  let clicked = 0;
  const nodes = [...document.querySelectorAll('button, [role=button], input[type=button], input[type=submit], a[href^="#"], .btn')];
  for (const node of nodes.slice(0, 80)) {
    if (/удал|очист|выход|reset all/i.test(node.textContent || '')) continue;
    try { node.click(); clicked++; } catch (e) { window.__yukiErrors.push(String(e)); }
  }
  for (const input of [...document.querySelectorAll('input[type=text], input:not([type]), input[type=number], textarea')].slice(0, 10)) {
    input.value = '12'; input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
  }
  for (const key of ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', ' ', 'Enter', '1', '+', '=', 'Escape']) {
    document.dispatchEvent(new KeyboardEvent('keydown', {key, bubbles: true}));
  }
  return clicked;
})()
"""

CATCH = """
window.__yukiErrors = [];
window.addEventListener('error', (e) => window.__yukiErrors.push(`${e.message} (${(e.filename||'').split('/').pop()}:${e.lineno})`));
window.addEventListener('unhandledrejection', (e) => window.__yukiErrors.push(String(e.reason)));
"""


def main(path: str) -> int:
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineScript
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1] + ["--headless"])
    console: list[str] = []

    class Page(QWebEnginePage):
        def javaScriptConsoleMessage(self, level, message, line, source):
            if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
                console.append(f"{message} ({source.split('/')[-1]}:{line})")

    page = Page()
    script = QWebEngineScript()
    script.setSourceCode(CATCH)
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    page.scripts().insert(script)
    result: dict = {"clicked": 0, "errors": []}

    def collect(raw) -> None:
        try:
            result["errors"] = json.loads(raw or "[]")
        except ValueError:
            pass
        app.quit()

    def clicked(count) -> None:
        result["clicked"] = int(count or 0)
        QTimer.singleShot(900, lambda: page.runJavaScript("JSON.stringify(window.__yukiErrors||[])", 0, collect))

    def loaded(ok: bool) -> None:
        if not ok:
            console.append("страница не открылась")
            app.quit()
            return
        QTimer.singleShot(700, lambda: page.runJavaScript(CLICK_ALL, 0, clicked))

    page.loadFinished.connect(loaded)
    page.load(QUrl.fromLocalFile(path))
    QTimer.singleShot(15000, app.quit)
    app.exec()
    errors = list(dict.fromkeys([*console, *result.get("errors", [])]))
    print(f"WEBROBOT clicked={result.get('clicked', 0)} errors={len(errors)}")
    for item in errors[:5]:
        print(item)
    sys.stdout.flush()
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
