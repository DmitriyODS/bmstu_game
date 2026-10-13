// Фон слайдов квиза: один и тот же слой рисуется на презентации, у участников
// и в предпросмотре конструктора.
// bg = {type: 'none'|'color'|'image', color, image, opacity: 0..100, blur: px, text_light}
const QuizBg = {
    isOn(bg) {
        return !!bg && ((bg.type === 'color' && !!bg.color) || (bg.type === 'image' && !!bg.image));
    },
    // Светлый текст нужен на тёмном фоне (с учётом того, насколько фон просвечивает).
    isDark(hex, opacity) {
        const n = parseInt(String(hex || '').slice(1), 16);
        if (Number.isNaN(n)) return false;
        const a = (opacity ?? 100) / 100;
        const mix = (c) => c * a + 248 * (1 - a);
        const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(mix);
        return (0.299 * r + 0.587 * g + 0.114 * b) < 140;
    },
    apply(host, bg, opts) {
        opts = opts || {};
        const on = QuizBg.isOn(bg);
        let layer = host.querySelector(':scope > .quiz-bg-layer');
        host.classList.toggle('has-quiz-bg', on);
        host.classList.toggle('quiz-bg-light-text', on && !!bg.text_light);
        if (!on) {
            if (layer) layer.remove();
            return;
        }
        if (!layer) {
            layer = document.createElement('div');
            layer.className = 'quiz-bg-layer';
            layer.setAttribute('aria-hidden', 'true');
            layer.appendChild(document.createElement('div'));
            host.prepend(layer);
        }
        Object.assign(layer.style, {
            position: opts.fixed ? 'fixed' : 'absolute', inset: '0', overflow: 'hidden',
            pointerEvents: 'none', zIndex: String(opts.zIndex ?? 0), background: opts.base || '',
        });
        const blur = bg.type === 'image' ? Math.max(0, Number(bg.blur) || 0) * (opts.scale ?? 1) : 0;
        const inner = layer.firstChild;
        inner.style.cssText = '';
        Object.assign(inner.style, {
            position: 'absolute',
            // Размытие делает края полупрозрачными — выносим их за пределы экрана.
            inset: `${-2 * blur}px`,
            opacity: String((bg.opacity ?? 100) / 100),
            filter: blur ? `blur(${blur}px)` : '',
        });
        if (bg.type === 'image') {
            inner.style.backgroundImage = `url(${JSON.stringify(opts.resolve ? opts.resolve(bg.image) : bg.image)})`;
            inner.style.backgroundSize = 'cover';
            inner.style.backgroundPosition = 'center';
        } else {
            inner.style.backgroundColor = bg.color;
        }
    },
};
