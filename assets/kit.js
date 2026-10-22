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

  window.Kit = { copy, SERVER: 'http://127.0.0.1:8770' };
})();
