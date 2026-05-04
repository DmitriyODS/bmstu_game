/* Бауманка.Квиз — клиентский менеджер звука.
   Единая точка управления всеми аудио-треками: вопросы, ответы, слайды,
   звуки таймера (start/mid/end), превью в редакторе. */
(function () {
    'use strict';

    // id -> {audio, timeout, category}
    const _tracks = new Map();
    let _mediaResolver = (url) => url;

    function _stop(id) {
        const t = _tracks.get(id);
        if (!t) return;
        if (t.timeout) { clearTimeout(t.timeout); t.timeout = null; }
        try { t.audio.pause(); } catch (_) {}
        try { t.audio.currentTime = 0; } catch (_) {}
        // Срываем src, чтобы браузер сразу освободил декодер.
        try { t.audio.removeAttribute('src'); t.audio.load(); } catch (_) {}
        _tracks.delete(id);
    }

    function _stopWhere(pred) {
        // Снимок ключей до удаления, чтобы не модифицировать map при итерации.
        [..._tracks.entries()].forEach(([id, t]) => { if (pred(t, id)) _stop(id); });
    }

    const AudioManager = {
        /** Резолвер URL — позволяет подменять путь на blob: из preload-кеша.
         *  По умолчанию — identity. */
        setMediaResolver(fn) {
            _mediaResolver = (typeof fn === 'function') ? fn : (u) => u;
        },

        /** Запустить трек.
         *  id — уникальный логический идентификатор (повторный play с тем же id глушит старый);
         *  opts: {url, category, loop, trimStart, trimEnd, volume, onEnd}.
         */
        play(id, opts) {
            opts = opts || {};
            if (!opts.url) return null;

            // Перекрыть свой же предыдущий запуск.
            _stop(id);
            // Перекрыть все треки той же категории (нужно для background).
            if (opts.category) {
                _stopWhere((t, otherId) => t.category === opts.category && otherId !== id);
            }

            const audio = new Audio(_mediaResolver(opts.url));
            audio.loop = !!opts.loop;
            if (opts.volume != null) audio.volume = opts.volume;

            const trimStart = Number(opts.trimStart) || 0;
            const trimEnd = (opts.trimEnd != null && opts.trimEnd !== '') ? Number(opts.trimEnd) : null;

            if (trimStart > 0) {
                const setStart = () => { try { audio.currentTime = trimStart; } catch (_) {} };
                if (audio.readyState >= 1) setStart();
                else audio.addEventListener('loadedmetadata', setStart, { once: true });
            }

            const entry = { audio, timeout: null, category: opts.category || null };
            _tracks.set(id, entry);

            const p = audio.play();
            if (p && typeof p.catch === 'function') p.catch(() => {});

            if (trimEnd != null && trimEnd > trimStart) {
                entry.timeout = setTimeout(
                    () => { if (_tracks.get(id) === entry) _stop(id); },
                    Math.max(0, (trimEnd - trimStart) * 1000)
                );
            }

            audio.addEventListener('ended', () => {
                if (_tracks.get(id) !== entry) return;
                if (typeof opts.onEnd === 'function') {
                    try { opts.onEnd(); } catch (_) {}
                }
                if (!audio.loop) _stop(id);
            }, { once: true });

            return entry;
        },

        stop(id) { _stop(id); },

        /** Остановить все треки заданной категории. */
        stopCategory(category) {
            if (!category) return;
            _stopWhere((t) => t.category === category);
        },

        /** Остановить вообще все треки. */
        stopAll() { _stopWhere(() => true); },

        isPlaying(id) {
            const t = _tracks.get(id);
            return !!(t && !t.audio.paused);
        },

        /** Узнать длительность файла (секунды). 0 при ошибке.
         *  Создаёт временный Audio только для metadata. */
        getDuration(url) {
            return new Promise((resolve) => {
                if (!url) return resolve(0);
                const a = new Audio();
                a.preload = 'metadata';
                let done = false;
                const finish = (v) => {
                    if (done) return; done = true;
                    try { a.removeAttribute('src'); a.load(); } catch (_) {}
                    resolve(isFinite(v) && v > 0 ? v : 0);
                };
                a.addEventListener('loadedmetadata', () => finish(a.duration), { once: true });
                a.addEventListener('error', () => finish(0), { once: true });
                a.src = _mediaResolver(url);
                a.load();
                // Страховка от зависания загрузки метаданных.
                setTimeout(() => finish(a.duration || 0), 8000);
            });
        },
    };

    window.AudioManager = AudioManager;
})();
