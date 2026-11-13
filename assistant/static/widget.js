// Віджет чату для сайту. Підключення: <script src="https://bot.example.com/static/widget.js" defer></script>
(function () {
  const API = (document.currentScript && new URL(document.currentScript.src).origin) || '';
  const KEY = 'support_session';

  let sessionId = localStorage.getItem(KEY);
  if (!sessionId) {
    sessionId = Math.random().toString(36).slice(2) + Date.now().toString(36);
    localStorage.setItem(KEY, sessionId);
  }

  const css = `
    .sw-btn{position:fixed;right:24px;bottom:24px;width:60px;height:60px;border:0;border-radius:50%;background:#16a34a;color:#fff;font-size:26px;cursor:pointer;box-shadow:0 8px 24px rgba(0,0,0,.2);z-index:9999}
    .sw-box{position:fixed;right:24px;bottom:96px;width:370px;max-width:calc(100vw - 32px);height:540px;max-height:calc(100vh - 120px);display:none;flex-direction:column;background:#fff;border-radius:16px;box-shadow:0 18px 50px rgba(0,0,0,.2);overflow:hidden;z-index:9999;font:14px/1.45 system-ui,sans-serif}
    .sw-box.open{display:flex}
    .sw-head{padding:14px 16px;background:#16a34a;color:#fff}
    .sw-head b{display:block;font-size:15px}.sw-head small{opacity:.85}
    .sw-log{flex:1;padding:14px;overflow-y:auto;background:#f6f7f9}
    .sw-msg{max-width:85%;margin:0 0 10px;padding:9px 12px;border-radius:14px;white-space:pre-wrap}
    .sw-user{margin-left:auto;background:#16a34a;color:#fff;border-bottom-right-radius:4px}
    .sw-bot{background:#fff;border:1px solid #e5e7eb;border-bottom-left-radius:4px}
    .sw-src{display:block;margin-top:6px;font-size:12px;color:#16a34a;text-decoration:none}
    .sw-note{font-size:12px;color:#92400e;background:#fef3c7;border-radius:8px;padding:6px 10px;margin:0 0 10px}
    .sw-quick{display:flex;flex-wrap:wrap;gap:6px;padding:8px 14px 0;background:#f6f7f9}
    .sw-quick button{border:1px solid #d1d5db;background:#fff;border-radius:99px;padding:5px 10px;font-size:12px;cursor:pointer}
    .sw-form{display:flex;gap:8px;padding:10px;border-top:1px solid #e5e7eb}
    .sw-form input{flex:1;padding:10px 12px;border:1px solid #d1d5db;border-radius:10px;font:inherit}
    .sw-form button{border:0;background:#16a34a;color:#fff;border-radius:10px;padding:0 14px;cursor:pointer}
    .sw-typing{color:#9ca3af;font-size:12px;margin:0 0 10px}
  `;
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);

  const box = document.createElement('div');
  box.className = 'sw-box';
  box.innerHTML = `
    <div class="sw-head"><b>Підтримка</b><small>Зазвичай відповідаємо одразу</small></div>
    <div class="sw-log"></div>
    <div class="sw-quick">
      <button>Скільки коштує доставка?</button>
      <button>Де моє замовлення?</button>
      <button>Хочу повернути товар</button>
    </div>
    <form class="sw-form"><input placeholder="Напишіть питання…" autocomplete="off"><button>➤</button></form>`;
  const btn = document.createElement('button');
  btn.className = 'sw-btn';
  btn.setAttribute('aria-label', 'Чат підтримки');
  btn.textContent = '💬';
  document.body.append(box, btn);

  const log = box.querySelector('.sw-log');
  const form = box.querySelector('form');
  const input = form.querySelector('input');

  function add(text, who, sources) {
    const el = document.createElement('div');
    el.className = `sw-msg sw-${who}`;
    el.textContent = text;
    (sources || []).filter((s) => s.url).slice(0, 2).forEach((s) => {
      const a = document.createElement('a');
      a.className = 'sw-src';
      a.href = s.url;
      a.target = '_blank';
      a.textContent = `📄 ${s.title}`;
      el.appendChild(a);
    });
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
  }

  async function send(text) {
    add(text, 'user');
    const typing = document.createElement('div');
    typing.className = 'sw-typing';
    typing.textContent = 'друкує…';
    log.appendChild(typing);

    try {
      const res = await fetch(`${API}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message: text }),
      });
      const data = await res.json();
      typing.remove();
      add(data.text, 'bot', data.sources);
      if (data.handoff) {
        const note = document.createElement('div');
        note.className = 'sw-note';
        note.textContent = 'Питання передано менеджеру';
        log.appendChild(note);
      }
    } catch (e) {
      typing.remove();
      add('Немає зв\'язку з сервером. Спробуйте ще раз або зателефонуйте: 0 800 30 30 30', 'bot');
    }
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    send(text);
  });
  box.querySelectorAll('.sw-quick button').forEach((b) => b.addEventListener('click', () => send(b.textContent)));

  btn.addEventListener('click', () => {
    box.classList.toggle('open');
    if (box.classList.contains('open') && !log.children.length) {
      add('Вітаю! Я асистент магазину. Питайте про доставку, оплату, повернення або статус замовлення.', 'bot');
    }
    input.focus();
  });

  window.SupportWidget = { open: () => btn.click(), send };
})();
