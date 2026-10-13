// Ознакомительный тур: затемняет страницу, подсвечивает элемент и показывает
// подсказку рядом. Шаги могут быть на разных страницах — позиция хранится в
// sessionStorage, после перехода тур продолжается сам.
//
// QuizTour.register('имя', [{url?, sel?, title, text}, ...]);
// QuizTour.start('имя');
(function () {
    const KEY = 'quizTour';
    const tours = {};
    let name = null, steps = null, idx = 0, target = null, ui = null, raf = 0;

    function readState() {
        try { return JSON.parse(sessionStorage.getItem(KEY) || 'null'); } catch (_) { return null; }
    }
    function writeState(state) {
        try {
            if (state) sessionStorage.setItem(KEY, JSON.stringify(state));
            else sessionStorage.removeItem(KEY);
        } catch (_) {}
    }

    function onPage(url) {
        if (!url) return true;
        const norm = (p) => p.replace(/\/+$/, '') || '/';
        return norm(new URL(url, location.href).pathname) === norm(location.pathname);
    }

    function build() {
        const blocker = document.createElement('div');
        blocker.className = 'fixed inset-0';
        blocker.style.zIndex = 1000;

        const hole = document.createElement('div');
        hole.className = 'rounded-xl pointer-events-none';
        Object.assign(hole.style, {
            position: 'fixed', zIndex: 1001,
            boxShadow: '0 0 0 200vmax rgba(15, 23, 42, 0.62)',
            transition: 'left .25s, top .25s, width .25s, height .25s',
        });

        const pop = document.createElement('div');
        pop.className = 'card bg-base-100 shadow-2xl border border-base-300 overflow-y-auto';
        pop.setAttribute('role', 'dialog');
        pop.setAttribute('aria-modal', 'true');
        pop.setAttribute('aria-labelledby', 'tour-title');
        Object.assign(pop.style, {
            position: 'fixed', zIndex: 1002, width: '22rem',
            maxWidth: 'calc(100vw - 1.5rem)', maxHeight: 'calc(100vh - 1.5rem)',
        });
        pop.innerHTML = `
            <div class="card-body p-4 gap-2">
                <div class="flex items-start justify-between gap-2">
                    <h2 id="tour-title" class="font-bold text-base leading-snug"></h2>
                    <button type="button" data-act="close" class="btn btn-ghost btn-xs btn-square shrink-0 -mr-1 -mt-1"
                            aria-label="Завершить тур" title="Завершить тур (Esc)">
                        <span class="material-symbols-outlined icon-sm" aria-hidden="true">close</span>
                    </button>
                </div>
                <div data-role="text" class="text-sm text-base-content/80 leading-relaxed"></div>
                <progress class="progress progress-primary h-1 mt-1" max="100" value="0" aria-hidden="true"></progress>
                <div class="flex items-center justify-between gap-2">
                    <span data-role="count" class="text-xs text-base-content/50"></span>
                    <div class="flex gap-2">
                        <button type="button" data-act="prev" class="btn btn-ghost btn-sm">Назад</button>
                        <button type="button" data-act="next" class="btn btn-primary btn-sm">Далее</button>
                    </div>
                </div>
            </div>`;
        pop.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-act]');
            if (!btn) return;
            if (btn.dataset.act === 'close') finish();
            else if (btn.dataset.act === 'prev') go(idx - 1);
            else go(idx + 1);
        });

        document.body.append(blocker, hole, pop);
        // Перехват на window в фазе capture: пока идёт тур, горячие клавиши
        // страниц (стрелки у судей и на пульте) срабатывать не должны.
        window.addEventListener('keydown', onKey, true);
        window.addEventListener('resize', schedulePlace);
        window.addEventListener('scroll', schedulePlace, true);
        return {blocker, hole, pop};
    }

    function onKey(e) {
        e.stopPropagation();
        if (e.key === 'Escape') { e.preventDefault(); finish(); }
        else if (e.key === 'ArrowRight') { e.preventDefault(); go(idx + 1); }
        else if (e.key === 'ArrowLeft') { e.preventDefault(); go(idx - 1); }
        else if (e.key === 'Tab') {
            // Фокус не уходит под затемнение.
            const items = [...ui.pop.querySelectorAll('button:not([disabled])')];
            const i = items.indexOf(document.activeElement);
            e.preventDefault();
            items[(i + (e.shiftKey ? -1 : 1) + items.length) % items.length].focus();
        }
    }

    function schedulePlace() {
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(place);
    }

    function place() {
        if (!ui) return;
        const vw = window.innerWidth, vh = window.innerHeight, pad = 6, gap = 12, edge = 12;
        const {hole, pop} = ui;
        const pw = pop.offsetWidth, ph = pop.offsetHeight;
        const clampX = (x) => Math.max(edge, Math.min(x, vw - pw - edge));
        const clampY = (y) => Math.max(edge, Math.min(y, vh - ph - edge));

        let r = null;
        if (target) {
            const b = target.getBoundingClientRect();
            const left = Math.max(b.left - pad, 4), top = Math.max(b.top - pad, 4);
            const right = Math.min(b.right + pad, vw - 4), bottom = Math.min(b.bottom + pad, vh - 4);
            // Скрытый или уехавший за экран элемент (меню на телефоне) — показываем шаг по центру.
            if (b.width > 0 && b.height > 0 && right - left > 16 && bottom - top > 16) {
                r = {left, top, right, bottom, width: right - left, height: bottom - top};
            }
        }

        if (!r) {
            Object.assign(hole.style, {left: `${vw / 2}px`, top: `${vh / 2}px`, width: '0', height: '0', outline: 'none'});
            pop.style.left = `${clampX((vw - pw) / 2)}px`;
            pop.style.top = `${clampY((vh - ph) / 2)}px`;
            return;
        }

        Object.assign(hole.style, {
            left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px`,
            outline: '2px solid oklch(var(--p))',
        });
        const cx = r.left + r.width / 2 - pw / 2, cy = r.top + r.height / 2 - ph / 2;
        let x, y;
        if (vh - r.bottom >= ph + gap + edge) { x = cx; y = r.bottom + gap; }
        else if (r.top >= ph + gap + edge) { x = cx; y = r.top - gap - ph; }
        else if (vw - r.right >= pw + gap + edge) { x = r.right + gap; y = cy; }
        else if (r.left >= pw + gap + edge) { x = r.left - gap - pw; y = cy; }
        else { x = cx; y = vh - ph - edge; }   // элемент во весь экран — подсказка поверх него
        pop.style.left = `${clampX(x)}px`;
        pop.style.top = `${clampY(y)}px`;
    }

    function go(i) {
        if (!steps || i < 0) return;
        if (i >= steps.length) { finish(); return; }
        const step = steps[i];
        const state = readState();
        let navigated = !!state && state.nav === i;
        // Шаг на другой странице — переходим один раз; если нас оттуда
        // перенаправили, показываем шаг по центру, а не уходим в цикл.
        if (!onPage(step.url)) {
            if (!navigated) {
                writeState({name, idx: i, nav: i});
                location.href = step.url;
                return;
            }
        } else {
            navigated = false;
        }
        idx = i;
        writeState({name, idx: i, nav: navigated ? i : null});

        if (!ui) ui = build();
        ui.pop.querySelector('#tour-title').textContent = step.title;
        ui.pop.querySelector('[data-role="text"]').innerHTML = step.text;
        ui.pop.querySelector('[data-role="count"]').textContent = `Шаг ${i + 1} из ${steps.length}`;
        ui.pop.querySelector('progress').value = Math.round((i + 1) / steps.length * 100);
        ui.pop.querySelector('[data-act="prev"]').classList.toggle('invisible', i === 0);
        const next = ui.pop.querySelector('[data-act="next"]');
        next.textContent = i === steps.length - 1 ? 'Готово' : 'Далее';

        target = step.sel ? document.querySelector(step.sel) : null;
        if (target) target.scrollIntoView({block: 'center', inline: 'nearest'});
        place();
        next.focus({preventScroll: true});
    }

    function finish() {
        writeState(null);
        cancelAnimationFrame(raf);
        if (ui) {
            window.removeEventListener('keydown', onKey, true);
            window.removeEventListener('resize', schedulePlace);
            window.removeEventListener('scroll', schedulePlace, true);
            Object.values(ui).forEach((el) => el.remove());
        }
        ui = null; steps = null; name = null; target = null;
    }

    function run(tourName, i) {
        if (!tours[tourName] || !tours[tourName].length) return;
        if (ui) finish();
        name = tourName;
        steps = tours[tourName];
        go(Math.min(i, steps.length - 1));
    }

    window.QuizTour = {
        register(tourName, list) { tours[tourName] = list; },
        start(tourName) { writeState({name: tourName, idx: 0, nav: null}); run(tourName, 0); },
    };

    // Продолжаем после перехода между страницами. load — чтобы страница
    // успела отрисовать то, что строит скриптами (структура в конструкторе).
    window.addEventListener('load', () => {
        if (window.self !== window.top) return;   // не в миниатюре презентации
        const state = readState();
        if (state && tours[state.name]) run(state.name, state.idx || 0);
    });
})();
