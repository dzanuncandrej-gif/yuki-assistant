/**
 * Знакомство с Юки: проверка системы, голос, имя и обучение на практике.
 *
 * Шаги озвучивает сама Юки. В уроках страница ждёт настоящую команду: человек
 * говорит её вслух (или пишет), Юки отвечает — и урок засчитывается по событиям
 * ядра, а не по нажатию кнопки «я сделал».
 */
import { connect, escapeHtml, parse } from './link.js';
import { createOrb } from './orb.js';

const SIGNALS = ['event', 'checks', 'profile'];
const SLOTS = ['ready', 'say', 'preview', 'setVoice', 'setName', 'runChecks', 'finish', 'startCall'];

const LESSONS = [
  {
    id: 'wake', title: 'Позови меня',
    say: 'Чтобы я тебя услышала, начни фразу с моего имени. Скажи: «Юки, который час?»',
    task: '«Юки, который час?»', expect: /котор[а-яё]*\s+час|сколько\s+времени|врем[яеи]/iu,
    facts: [['Без обращения', 'После моего ответа 20 секунд можно говорить без имени.'], ['Перебить', 'Скажи «стоп» или просто заговори — я замолчу.']],
  },
  {
    id: 'action', title: 'Действия',
    say: 'Я управляю компьютером: звуком, окнами, программами, файлами. Попробуй: «Юки, громкость тридцать».',
    task: '«Юки, громкость 30»', expect: /громкост|звук/i,
    facts: [['Программы', '«Открой телеграм», «закрой хром», «сверни всё».'], ['Медиа', '«Следующий трек», «пауза» — я проверю, что переключилось.']],
  },
  {
    id: 'screen', title: 'Зрение',
    say: 'Я вижу твой экран: читаю текст и понимаю картинки. Спроси: «Юки, что у меня на экране?»',
    task: '«Юки, что у меня на экране?»', expect: /экран|видишь|изображен/i,
    facts: [['Ошибки', '«Что это за ошибка?» — объясню причину и что сделать.'], ['Кнопки', '«Нажми Сохранить» — найду кнопку и нажму точно.']],
  },
  {
    id: 'deep', title: 'Разборы',
    say: 'Сложные вопросы я разбираю подробно: суть скажу голосом, а весь разбор покажу на экране. Попробуй: «Юки, объясни подробно, как работает интернет».',
    task: '«Юки, объясни подробно, как работает интернет»', expect: /объясни|подробн|разбер|сравни/i,
    facts: [['Поиск', 'Вопросы о ценах, новостях и фактах я сначала ищу в интернете.'], ['Утро', '«Доброе утро» — погода, напоминания и кто писал, одним рассказом.']],
  },
  {
    id: 'agent', title: 'Агент',
    say: 'Я пишу программы целиком: продумываю, пишу код, запускаю и сама исправляю ошибки. Попробуй: «Юки, напиши калькулятор».',
    task: '«Юки, напиши калькулятор»', expect: /напиши|создай|сделай|программ|проект|калькулятор/i,
    facts: [['Вкладка «Агент»', 'Там видно, как появляется код, — и папка готового проекта.'], ['Ошибки', '«Что за ошибка?» — найду причину и положу исправление в буфер.']],
  },
  {
    id: 'music', title: 'Своя музыка',
    say: 'Добавь любимые песни во вкладку «Плейлист» и говори: «Юки, включи мою музыку». Без рекламы и случайных роликов.',
    task: '«Юки, включи мою музыку»', expect: /музык|плейлист|песн/i,
    facts: [['Управление', '«Следующая», «пауза», «перемешай», «что играет».'], ['Тише', 'Пока я говорю, музыка сама становится тише.']],
  },
  {
    id: 'messages', title: 'Сообщения',
    say: 'Я пишу людям в Телеграм. Скажи, например: «Юки, напиши в избранное привет». Своих людей добавь в меню «Сообщения» — тогда я найду их сразу.',
    task: '«Юки, напиши в избранное привет»', expect: /напиши|отправь|скинь|избранн/i,
    facts: [['Входящие', '«Что мне писали?» — перескажу, кто и о чём, ничего не открывая.'], ['Ответ', '«Что мне ему ответить?» — предложу три варианта.']],
  },
  {
    id: 'call', title: 'Видеосвязь',
    say: 'И главное: мы можем созвониться. Скажи «Юки, давай созвонимся» или нажми Ctrl+D. В звонке я вижу экран, слышу тебя без имени и понимаю жесты.',
    task: '«Юки, давай созвонимся»  ·  Ctrl+D', expect: /созвон|видеосвяз|видеозвон/i,
    facts: [['Жесты', 'Ладонь — тишина, два пальца — следующий трек, кулак — микрофон.'], ['В угол', 'Esc сворачивает звонок в маленькое окно поверх всех.']],
  },
];

const STEPS = ['Привет', 'Проверка', 'Голос', 'Имя', 'Обучение', 'Готово'];

const $ = (id) => document.getElementById(id);
const body = $('body');
const subtitle = $('subtitle');
let link = null;
let orb = null;
let step = 0;
let lesson = 0;
let checks = [];
let profile = { voices: [], voice: '', name: '' };
let lessonState = 'idle';   // idle → heard → done
let subTimer = 0;
const done = new Set();

try {
  orb = createOrb(document.querySelector('.gl'), { count: 30000, zoom: 12, size: 1.45 });
  orb.place(0, 0.1, 0.9);
  orb.mode('greeting');
} catch (err) {
  console.warn('WebGL недоступен', err);
}

function speak(text) {
  link?.say(text);
}

function renderSteps() {
  $('steps').innerHTML = STEPS.map((name, i) =>
    `<li class="${i === step ? 'is-now' : i < step ? 'is-done' : ''}" title="${name}"><b>${i < step ? '✓' : i + 1}</b>${i === step ? name : ''}</li>`).join('');
  $('back').disabled = step === 0;
  $('next').textContent = step === STEPS.length - 1 ? 'Начать' : step === 4 ? 'Пропустить урок' : 'Дальше';
}

function go(index) {
  step = Math.max(0, Math.min(STEPS.length - 1, index));
  renderSteps();
  body.style.animation = 'none';
  void body.offsetWidth;
  body.style.animation = '';
  [welcome, systemCheck, voiceStep, nameStep, lessonStep, finishStep][step]();
}

/* ------------------------------------------------------------------ шаги */

function welcome() {
  orb?.mode('greeting');
  body.innerHTML = `
    <span class="kicker">Знакомство · 3 минуты</span>
    <h1>Привет! Я Юки — твой голосовой помощник</h1>
    <p class="lead">Я живу на твоём компьютере: слышу, вижу экран, управляю программами и отвечаю голосом. Всё работает локально, без подписок.</p>
    <p class="lead">Сейчас проверим, что всё готово, выберем мой голос — и я покажу, что умею, на практике.</p>`;
  speak('Привет! Я Юки, твой голосовой помощник. Давай проверим, что всё готово, выберем мне голос, и я покажу, что умею.');
}

const CHECK_ICON = { ok: '✓', warn: '!', bad: '×', wait: '' };

function renderChecks() {
  const list = body.querySelector('.checks');
  if (!list) return;
  list.innerHTML = checks.map((c) => `
    <li class="check" data-state="${c.state}">
      <span class="check__dot">${CHECK_ICON[c.state] ?? ''}</span>
      <div><b>${escapeHtml(c.title)}</b><small>${escapeHtml(c.detail || '')}</small>
        ${c.fix ? `<small class="fix">${escapeHtml(c.fix)}</small>` : ''}</div>
      ${c.id === 'mic' ? '<div class="meter" aria-hidden="true"><i id="mic-level"></i></div>' : '<span></span>'}
    </li>`).join('');
}

function systemCheck() {
  orb?.mode('thinking');
  body.innerHTML = `
    <span class="kicker">Шаг 2 · проверка</span>
    <h1>Проверяю, всё ли готово</h1>
    <p class="lead">Скажи что-нибудь — полоска у микрофона должна прыгать.</p>
    <ul class="checks"></ul>`;
  checks = [
    { id: 'model', title: 'Мозг на видеокарте', state: 'wait', detail: 'проверяю…' },
    { id: 'mic', title: 'Микрофон', state: 'wait', detail: 'проверяю…' },
    { id: 'voice', title: 'Голос', state: 'wait', detail: 'проверяю…' },
    { id: 'eyes', title: 'Зрение', state: 'wait', detail: 'проверяю…' },
  ];
  renderChecks();
  link?.runChecks();
  speak('Проверяю систему. Скажи что-нибудь, чтобы я проверила микрофон.');
}

function voiceStep() {
  orb?.mode('speaking');
  body.innerHTML = `
    <span class="kicker">Шаг 3 · голос</span>
    <h1>Каким голосом мне говорить?</h1>
    <p class="lead">Нажми «Послушать», чтобы услышать голос, и выбери карточку. Поменять можно в любой момент в меню.</p>
    <div class="voices">${profile.voices.map((v) => `
      <button type="button" class="voice-card ${v.key === profile.voice ? 'is-on' : ''}" data-key="${v.key}">
        <div class="row"><h3>${escapeHtml(v.title)}</h3><span class="tag">${v.gender === 'm' ? 'мужской' : 'женский'}</span></div>
        <p>${escapeHtml(v.character)}</p>
        <div class="row">${v.key === profile.voice ? '<span class="tag">выбран</span>' : '<span></span>'}<span class="listen" data-listen="${v.key}">Послушать</span></div>
      </button>`).join('')}</div>`;
  body.querySelectorAll('.voice-card').forEach((card) => card.addEventListener('click', (e) => {
    const key = card.dataset.key;
    if (e.target.closest('[data-listen]')) { link?.preview(key); return; }
    profile.voice = key;
    link?.setVoice(key);
    voiceStep();
  }));
}

function nameStep() {
  orb?.mode('listening');
  body.innerHTML = `
    <span class="kicker">Шаг 4 · знакомство</span>
    <h1>Как к тебе обращаться?</h1>
    <p class="lead">Буду звать тебя по имени — но не в каждой фразе.</p>
    <form class="field" id="name-form"><input id="name" maxlength="40" placeholder="Твоё имя" value="${escapeHtml(profile.name || '')}" aria-label="Имя"><button class="btn btn--primary" type="submit">Запомнить</button></form>`;
  const input = $('name');
  input.focus();
  $('name-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const value = input.value.trim();
    if (!value) return;
    profile.name = value;
    link?.setName(value);
    speak(`Приятно познакомиться, ${value}!`);
    setTimeout(() => go(4), 1400);
  });
  speak('Как к тебе обращаться?');
}

function lessonStep() {
  const item = LESSONS[lesson];
  lessonState = 'idle';
  orb?.mode('idle');
  body.innerHTML = `
    <div class="lesson">
      <span class="kicker">Урок ${lesson + 1} из ${LESSONS.length} · ${escapeHtml(item.title)}</span>
      <h1>${escapeHtml(item.say.split('.')[0])}.</h1>
      <div class="task" id="task"><span>Скажи вслух или напиши в «Диалоге»</span><p>${escapeHtml(item.task)}</p></div>
      <p class="heard" id="heard">Жду твою команду…</p>
      <div class="facts">${item.facts.map(([t, d]) => `<div class="fact"><b>${escapeHtml(t)}</b>${escapeHtml(d)}</div>`).join('')}</div>
      ${item.id === 'call' ? '<button class="btn btn--primary" id="try-call" type="button">Позвонить сейчас</button>' : ''}
    </div>`;
  $('try-call')?.addEventListener('click', () => link?.startCall());
  speak(item.say);
}

function finishStep() {
  orb?.mode('greeting');
  const learned = done.size;
  body.innerHTML = `
    <span class="kicker">Готово</span>
    <h1>${profile.name ? `${escapeHtml(profile.name)}, я` : 'Я'} готова к работе</h1>
    <p class="lead">Ты прошёл ${learned} из ${LESSONS.length} уроков. Это знакомство можно повторить в любой момент: клавиша F1 или пункт «Обучение» в трее.</p>
    <div class="facts">
      <div class="fact"><b>Ctrl+Alt+J</b>показать или спрятать окно</div>
      <div class="fact"><b>Ctrl+D</b>видеосвязь</div>
      <div class="fact"><b>Ctrl+Space</b>замолчать</div>
      <div class="fact"><b>«Юки, что ты умеешь?»</b>я расскажу сама</div>
    </div>`;
  speak('Всё готово! Я рядом — просто позови меня по имени.');
}

/* ------------------------------------------------------------------ события ядра */

function lessonEvent(ev) {
  if (step !== 4) return;
  const item = LESSONS[lesson];
  if (ev.type === 'message' && ev.kind === 'user' && lessonState === 'idle' && item.expect.test(ev.text || '')) {
    lessonState = 'heard';
    $('task')?.classList.add('is-heard');
    const heard = $('heard');
    if (heard) heard.innerHTML = `Слышу: <b>«${escapeHtml(ev.text)}»</b> — выполняю…`;
    orb?.mode('thinking');
  } else if (lessonState === 'heard' && ev.type === 'message' && (ev.kind === 'assistant' || ev.kind === 'report')) {
    lessonState = 'done';
    done.add(item.id);
    $('task')?.classList.add('is-done');
    const heard = $('heard');
    if (heard) heard.innerHTML = '<b>Получилось!</b> Переходим дальше…';
    orb?.pulse(1);
    setTimeout(nextLesson, 2600);
  } else if (ev.type === 'ui' && ev.action === 'start_call' && item.id === 'call') {
    done.add('call');
    setTimeout(nextLesson, 1500);
  }
}

function nextLesson() {
  if (step !== 4) return;
  if (lesson < LESSONS.length - 1) {
    lesson += 1;
    lessonStep();
  } else {
    go(5);
  }
}

function onEvent(raw) {
  const ev = parse(raw);
  if (!ev) return;
  if (ev.type === 'level' && step === 1) {
    const bar = $('mic-level');
    if (bar) bar.style.width = `${Math.min(100, (ev.level || 0) * 140)}%`;
    if ((ev.level || 0) > 0.12) {
      const mic = checks.find((c) => c.id === 'mic');
      if (mic && mic.state !== 'ok' && mic.heard !== true) {
        mic.heard = true; mic.state = 'ok'; mic.detail = `${mic.device || 'микрофон'} — слышу тебя`;
        mic.fix = ''; renderChecks();
      }
    }
  }
  if (ev.type === 'speech') {
    subtitle.textContent = ev.text || '';
    clearTimeout(subTimer);
    subTimer = setTimeout(() => { subtitle.textContent = ''; }, 5000);
  }
  if (ev.type === 'level' && orb) orb.target.amp = Math.min(0.6, (ev.level || 0) * 0.55);
  lessonEvent(ev);
}

/* ------------------------------------------------------------------ навигация */

$('next').addEventListener('click', () => {
  if (step === 4) { nextLesson(); return; }
  if (step === STEPS.length - 1) { link?.finish(); return; }
  go(step + 1);
});
$('back').addEventListener('click', () => {
  if (step === 4 && lesson > 0) { lesson -= 1; lessonStep(); return; }
  go(step - 1);
});
$('close').addEventListener('click', () => link?.finish());
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') link?.finish(); });

connect(SIGNALS, SLOTS).then((created) => {
  link = created;
  link.event.connect(onEvent);
  link.checks.connect((raw) => {
    const incoming = parse(raw) || [];
    incoming.forEach((c) => {
      const old = checks.find((item) => item.id === c.id);
      if (old && old.heard && c.id === 'mic') return;  // микрофон уже услышал человека
      if (old) Object.assign(old, c); else checks.push(c);
    });
    renderChecks();
  });
  link.profile.connect((raw) => {
    profile = { ...profile, ...(parse(raw) || {}) };
    if (step === 2) voiceStep();
  });
  link.ready();
  go(0);
}).catch((err) => console.error(err));
