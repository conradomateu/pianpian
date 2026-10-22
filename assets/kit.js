/* Mandarin Kit: theme switch and copy-to-clipboard, shared by every page.
   The inline snippet in each <head> applies the saved theme before paint. */
(function () {
  const KEY = 'zh-kit-theme', MODES = ['system', 'light', 'dark'], LABEL = { system: 'Auto', light: 'Light', dark: 'Dark' };

  function setTheme(mode, btn) {
    if (mode === 'system') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', mode);
    if (btn) btn.textContent = LABEL[mode];
    try { localStorage.setItem(KEY, mode); } catch {}
  }

  async function copy(text, btn) {
    try { await navigator.clipboard.writeText(text); }
    catch {                                     // file:// and older browsers
      const ta = Object.assign(document.createElement('textarea'), { value: text });
      document.body.append(ta); ta.select(); document.execCommand('copy'); ta.remove();
    }
    if (btn) {
      const old = btn.textContent;
      btn.textContent = 'Copied ✓'; btn.classList.add('ok');
      setTimeout(() => { btn.textContent = old; btn.classList.remove('ok'); }, 1300);
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.querySelector('[data-theme-toggle]');
    let mode = 'system'; try { mode = localStorage.getItem(KEY) || 'system'; } catch {}
    setTheme(mode, btn);
    if (btn) btn.addEventListener('click', () => { mode = MODES[(MODES.indexOf(mode) + 1) % 3]; setTheme(mode, btn); });
  });

  /* FLIP: change the layout at once, then glide every element from where it was to where it is.
     Only transforms animate, so the video and the buttons move together and nothing is laid out
     again on each frame. Elements in `scale` also grow or shrink (the video); the rest only move. */
  const EASE = 'cubic-bezier(.2,.8,.2,1)', DURATION = 340;
  function flip(targets, change, scale = []) {
    const els = targets.filter(Boolean);
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) { change(); return; }
    const before = new Map(els.map(e => [e, e.getBoundingClientRect()]));
    change();
    for (const e of els) {
      const a = before.get(e), b = e.getBoundingClientRect();
      if (!a.width || !b.width) continue;
      const dx = a.left - b.left, dy = a.top - b.top;
      const sx = scale.includes(e) ? a.width / b.width : 1, sy = scale.includes(e) ? a.height / b.height : 1;
      if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5 && Math.abs(sx - 1) < 0.005 && Math.abs(sy - 1) < 0.005) continue;
      e.animate([{ transformOrigin: '0 0', transform: `translate(${dx}px, ${dy}px) scale(${sx}, ${sy})` },
                 { transformOrigin: '0 0', transform: 'none' }], { duration: DURATION, easing: EASE });
    }
  }

  window.Kit = { copy, flip, SERVER: 'http://127.0.0.1:8770' };
})();
