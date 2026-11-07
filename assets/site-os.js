/* Landing page: put the visitor's download first and say whether their computer can run Pianpian.
   Progressive enhancement: both download buttons are always there; this only reorders them and adds a line.
   What browsers tell (checked 7 Nov 2026 against their docs, not on every device): Chromium gives
   userAgentData and architecture/bitness/platformVersion hints; Safari and Firefox give none, and Safari's
   user agent says "Intel Mac" on Apple Silicon too, so a WebGL renderer name is only a hint. */
(() => {
  const NEEDS_MAC = 'Needs Apple Silicon (M1 or newer) and macOS 14+.';
  const NEEDS_WIN = 'Needs 64-bit Windows (x64). Windows 11 is tested; Windows 10 isn’t tested yet; Windows on ARM isn’t supported yet.';

  /* {ua, platform, touch, hints, gpu} → {os: 'mac'|'windows'|'other', fits: true|false|null, note}.
     fits null = can't tell from this browser. Pure, so tests/test_site_os.py runs it over sample browsers. */
  function classify({ ua = '', platform = '', touch = 0, hints = {}, gpu = '' } = {}) {
    const arch = hints.architecture || '';
    const major = parseInt(hints.platformVersion, 10);
    if (/iPhone|iPad|iPod|Android/.test(ua) || (/Macintosh/.test(ua) && touch > 1))   // iPadOS asks for the Mac page
      return { os: 'other', fits: false, note: 'Pianpian runs on Mac and Windows. Open this page on your computer.' };
    if (platform === 'macOS' || /Macintosh|Mac OS X/.test(ua)) {
      if (arch === 'x86') return { os: 'mac', fits: false, note: 'Your browser reports an Intel Mac. Pianpian needs Apple Silicon (M1 or newer).' };
      if (arch === 'arm') {
        if (major > 0 && major < 14) return { os: 'mac', fits: false, note: `This Mac reports macOS ${major}. Pianpian needs macOS 14 or newer.` };
        return { os: 'mac', fits: major >= 14 ? true : null, note: major >= 14 ? 'This Mac has Apple Silicon and macOS 14+.' : 'This Mac has Apple Silicon. Pianpian needs macOS 14 or newer.' };
      }
      if (/Apple M\d/.test(gpu)) return { os: 'mac', fits: null, note: 'This looks like an Apple Silicon Mac. Pianpian needs macOS 14 or newer.' };
      return { os: 'mac', fits: null, note: NEEDS_MAC };
    }
    if (platform === 'Windows' || /Windows NT/.test(ua)) {
      if (arch === 'arm') return { os: 'windows', fits: false, note: 'Windows on ARM isn’t supported yet. Pianpian needs a 64-bit Intel or AMD PC (x64).' };
      if (arch === 'x86' && hints.bitness === '32') return { os: 'windows', fits: false, note: 'Pianpian needs 64-bit Windows (x64).' };
      if (arch === 'x86' && hints.bitness === '64') {
        if (major >= 13) return { os: 'windows', fits: true, note: 'Windows 11 x64: the tested setup.' };   // platformVersion 13+ is Windows 11
        if (major >= 1) return { os: 'windows', fits: null, note: 'Windows 10 x64: the installer allows it, but it isn’t tested yet. Windows 11 is tested.' };
      }
      return { os: 'windows', fits: null, note: NEEDS_WIN };
    }
    if (/Linux|CrOS|X11/.test(ua + platform)) return { os: 'other', fits: false, note: 'Pianpian runs on Mac (Apple Silicon) and Windows (x64); there is no Linux app.' };
    return { os: 'other', fits: false, note: 'Pianpian runs on Mac and Windows. Open this page on your computer.' };
  }

  async function probe(nav = navigator) {
    const data = nav.userAgentData;
    let hints = {}, gpu = '';
    try { if (data?.getHighEntropyValues) hints = await data.getHighEntropyValues(['architecture', 'bitness', 'platformVersion']); } catch { /* refused: no hints */ }
    if (!hints.architecture && /Mac/.test(nav.userAgent)) {
      try {
        const gl = document.createElement('canvas').getContext('webgl');
        const info = gl && gl.getExtension('WEBGL_debug_renderer_info');
        gpu = (info && gl.getParameter(info.UNMASKED_RENDERER_WEBGL)) || '';
      } catch { /* no WebGL */ }
    }
    return { ua: nav.userAgent, platform: data?.platform || '', touch: nav.maxTouchPoints || 0, hints, gpu };
  }

  async function apply() {
    const cta = document.getElementById('download');
    if (!cta) return;
    const seen = classify(await probe());
    const note = document.getElementById('os-note');
    note.textContent = seen.note;
    note.dataset.fits = seen.fits;
    note.hidden = false;
    for (const el of document.querySelectorAll('[data-umami-event="download"]')) el.dataset.umamiEventDetected = seen.os;
    if (seen.os === 'other') return;
    for (const pair of document.querySelectorAll('.cta')) {
      const mine = pair.querySelector(`[data-os="${seen.os}"]`);
      if (mine) pair.prepend(mine);
    }
    // the header button downloads directly only when this computer is one Pianpian supports or might support
    const button = cta.querySelector(`a[data-os="${seen.os}"]`), head = document.querySelector('header.top .dl');
    if (button && seen.fits !== false && head) {
      head.href = button.href;
      head.dataset.umamiEventOs = seen.os;
      head.querySelector('svg')?.remove();
      head.prepend(button.querySelector('svg').cloneNode(true));
    }
  }

  window.PianpianOS = { classify };
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', apply);
    else apply();
  }
})();
