/* Subtitle player: one <video> with any number of .srt/.vtt tracks stacked on it.
   Used by app.html, for videos from the local server and for files dropped on the window.

     const p = SubPlayer.mount(element, { hint: 'html shown before a video is loaded' });
     p.load({ video: url-or-File, subs: [{ name, text }], words: zh.words.json (optional),
              id: 'remembers the cover band per video', cover: true-if-subtitles-are-burned-in });

   With zh.words.json (made by srt_tool.py words) each Chinese word is linked to its pinyin and,
   through its dictionary meaning (CC-CEDICT), to the English words that translate it: hover any of
   them and all three light up with the meaning shown; click to pin; or show pinyin above words.

   Each track has its own on/off, size, colour and "blur while playing" (test yourself; it shows
   when you pause). Size, colour and blur are remembered per kind of line (中文 / pinyin / English);
   which lines are on is remembered per video, so turning yours off for a video that already has
   subtitles in the picture leaves the others alone. */
(function () {
  const COLOUR = { zh: '#ffffff', pinyin: '#ffd75e', en: '#9fd8ff', stacked: '#c8f0c0', other: '#c8f0c0' };
  const SCALE = { zh: 1, pinyin: 0.8, en: 0.85, stacked: 0.8, other: 0.85 };
  const LABEL = { zh: '中文', pinyin: 'Pinyin', en: 'English', stacked: 'stacked', other: 'track' };
  const ORDER = { zh: 0, pinyin: 1, en: 2, stacked: 3, other: 4 };
  const PREFS = 'zh-player-v2';
  const RESOURCES = [                               // the Resources dropdown: free, well-known references
    ['Pleco', 'https://www.pleco.com', 'Dictionary app for phone: handwriting, flashcards'],
    ['MDBG', 'https://www.mdbg.net/chinese/dictionary', 'Online dictionary (CC-CEDICT, the one the player uses)'],
    ['Chinese Grammar Wiki', 'https://resources.allsetlearning.com/chinese/grammar/', 'Grammar points by HSK level, with examples'],
    ['Anki', 'https://apps.ankiweb.net', 'Spaced-repetition flashcards'],
    ['Bilibili search', 'https://search.bilibili.com', 'Find videos to paste into the library'],
  ];
  const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');

  /* ---- tone colours: split a word's pinyin into syllables and read each one's tone mark ----
     Valid syllables come from pypinyin's data (423) plus lü/nü; a word's pinyin is split so it has as
     many syllables as the word has characters (erhua: 一点儿 yìdiǎnr ends in a bare r). */
  const SYL = new Set(('a ai an ang ao ba bai ban bang bao bei ben beng bi bian biang biao bie bin bing bo bong bu ca cai can cang cao ce cei cen ceng cha chai chan chang chao che chen cheng chi chong chou chu chua chuai chuan chuang chui chun chuo ci cong cou cu cuan cui cun cuo da dai dan dang dao de dei den deng di dia dian diao die din ding diu dong dou du duan dui dun duo e ei en eng er fa fan fang fei fen feng fiao fo fou fu ga gai gan gang gao ge gei gen geng gong gou gu gua guai guan guang gui gun guo ha hai han hang hao he hei hen heng hm hng hong hou hu hua huai huan huang hui hun huo ji jia jian jiang jiao jie jin jing jiong jiu ju juan jue jun ka kai kan kang kao ke kei ken keng kong kou ku kua kuai kuan kuang kui kun kuo la lai lan lang lao le lei len leng li lia lian liang liao lie lin ling liu lo long lou lu luan lue lun luo lv lve m ma mai man mang mao me mei men meng mi mian miao mie min ming miu mo mou mu n na nai nan nang nao ne nei nen neng ng ni nia nian niang niao nie nin ning niu nong nou nu nuan nue nun nuo nv nve o ou pa pai pan pang pao pei pen peng pi pian piao pie pin ping po pou pu qi qia qian qiang qiao qie qin qing qiong qiu qu quan que qun ran rang rao re ren reng ri rong rou ru rua ruan rui run ruo sa sai san sang sao se sen seng sha shai shan shang shao she shei shen sheng shi shou shu shua shuai shuan shuang shui shun shuo si song sou su suan sui sun suo ta tai tan tang tao te tei teng ti tian tiao tie ting tong tou tu tuan tui tun tuo wa wai wan wang wei wen weng wo wong wu xi xia xian xiang xiao xie xin xing xiong xiu xu xuan xue xun ya yan yang yao ye yi yin ying yo yong you yu yuan yue yun za zai zan zang zao ze zei zen zeng zha zhai zhan zhang zhao zhe zhei zhen zheng zhi zhong zhou zhu zhua zhuai zhuan zhuang zhui zhun zhuo zi zong zou zu zuan zui zun zuo').split(' '));
  const TONE_MARK = { '̄': 1, '́': 2, '̌': 3, '̀': 4 };
  function syllables(py, n) {          // "xiānsheng", 2 -> [["xiān", 1], ["sheng", 5]]; null if it can't be split
    const chars = [...py.normalize('NFC')].map(c => {
      const d = c.normalize('NFD');
      return { c, base: d[0] === 'ü' || d[0] === 'Ü' || d.startsWith('ü') ? 'v' : d[0].toLowerCase(), tone: TONE_MARK[[...d].find(x => TONE_MARK[x])] || 0 };
    });
    const best = new Map();
    const go = i => {                    // fewest pieces that are all syllables (with an exact count preferred)
      if (i === chars.length) return [];
      if (best.has(i)) return best.get(i);
      let out = null;
      if (chars[i].c === "'" || chars[i].c === '-') { const r = go(i + 1); best.set(i, r); return r; }
      for (let j = Math.min(chars.length, i + 6); j > i; j--) {
        const s = chars.slice(i, j).map(x => x.base).join('');
        const tail = j === chars.length && s === 'r' && i > 0;          // erhua
        if (!SYL.has(s) && !tail) continue;
        const rest = go(j);
        if (rest && (!out || rest.length + 1 < out.length)) out = [[i, j], ...rest];
      }
      best.set(i, out); return out;
    };
    const parts = go(0);
    if (!parts || (n && parts.length !== n && !(parts.length === n + 1 && py.endsWith('r')))) return null;
    return parts.map(([i, j]) => [chars.slice(i, j).map(x => x.c).join(''), chars.slice(i, j).reduce((t, x) => x.tone || t, 0) || 5]);
  }
  const toned = (py, zh) => {           // pinyin with each syllable in its tone's colour (falls back to plain text)
    const n = [...zh].filter(c => /[一-鿿]/.test(c)).length;
    const parts = syllables(py, n - (/儿$/.test(zh) && /r$/.test(py) && n > 1 ? 1 : 0));
    return parts ? parts.map(([s, t]) => `<s class="t${t}">${esc(s)}</s>`).join('') : esc(py);
  };

  /* ---- tense marks (zh.words.json "g", made by pipeline/grammar.py) ---- */
  const RULES = {
    'past:le': ['past', '了 after a verb: the action is done'],
    'past:guo': ['past', '过 after a verb: you have done it before'],
    'past:mei': ['past', '没 / 没有 + verb: it did not happen (no 了 after it)'],
    'present:zai': ['present', '在 / 正在 + verb: happening right now'],
    'present:zhe': ['present', '着 after a verb: an ongoing state'],
    'future:jiang': ['future', '将 + verb: will (formal)'],
    'future:kuaiyao': ['future', '快要 / 就要 … 了: about to happen'],
    'maybe:hui': ['maybe future', '会 + verb: will, or "can" (a skill). The context decides'],
    'maybe:yao': ['maybe future', '要 + verb: going to, or "want to". The context decides'],
    'change:le': ['new situation', '了 at the end, not after a verb: something has changed'],
    'time-past': ['past', 'a time word for the past'],
    'time-present': ['present', 'a time word for now'],
    'time-future': ['future', 'a time word for the future'],
  };

  function tsec(t) {
    const m = t.trim().replace(',', '.').match(/(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)/);
    return m ? (+(m[1] || 0)) * 3600 + (+m[2]) * 60 + parseFloat(m[3]) : NaN;
  }
  function parse(text) {
    const out = [];
    for (const block of text.replace(/^﻿/, '').replace(/\r/g, '').split(/\n\s*\n/)) {
      const lines = block.trim().split('\n'), i = lines.findIndex(l => l.includes('-->'));
      if (i < 0) continue;
      const [a, b] = lines[i].split('-->'), s = tsec(a), e = tsec(b.trim().split(/\s/)[0]);
      const body = lines.slice(i + 1).join('\n').replace(/<[^>]+>/g, '').replace(/\{\\[^}]*\}/g, '').trim();
      if (!isNaN(s) && !isNaN(e) && body) out.push({ s, e, text: body });
    }
    return out.sort((x, y) => x.s - y.s);
  }
  function roleOf(name) {
    const n = name.toLowerCase();
    if (/trilingual|zh-pinyin|zh\+/.test(n)) return 'stacked';
    if (/pinyin/.test(n)) return 'pinyin';
    if (/(^|[._\- ])(en|eng|english)([._\- ]|$)/.test(n)) return 'en';
    return 'zh';
  }
  function cueAt(cues, t) {                         // last cue starting at or before t, if it still covers t
    let lo = 0, hi = cues.length - 1, r = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (cues[m].s <= t) { r = m; lo = m + 1; } else hi = m - 1; }
    return r >= 0 && cues[r].e > t ? r : -1;
  }

  function mount(root, opts = {}) {
    // Everything below the video is one row of dropdowns ([data-extra] is where a page adds its own).
    // The transcript goes into opts.list when the page gives one (app.html: its right panel).
    root.innerHTML = `
      <div class="pl${opts.list ? ' nolist' : ''}">
        <div class="pmain">
          <div class="stage" style="--size:5.2;--lift:6">
            <video playsinline></video><div class="cover" hidden></div><div class="ov bg"></div>
            <div class="vc">
              <button data-play title="play / pause (Space)">▶</button>
              <button data-vprev title="previous line (←)">⏮</button><button data-vnext title="next line (→)">⏭</button>
              <span data-time>0:00 / 0:00</span>
              <input type="range" data-seek min="0" max="1000" value="0" title="seek">
              <button data-vspeed title="speed">1×</button>
              <button data-vfull title="fullscreen (F, or double-click the video)">⛶</button>
            </div>
            <div class="drop">${opts.hint || ''}</div>
          </div>
          <div class="pbar">
            <details class="dd" data-dd><summary>Subtitles</summary><div class="ddp wide">
              <div class="row" data-presets></div>
              <h5>Tracks · top to bottom · size · colour · blur while playing</h5>
              <div data-tracks><span class="muted">No subtitles loaded.</span></div>
              <div class="row">
                <label class="check">Size <input type="range" data-size min="2.5" max="9" step=".1" value="5.2"></label>
                <label class="check">Lift <input type="range" data-lift min="0" max="40" step=".5" value="6"></label>
              </div>
              <div class="row">
                <button class="btn" data-ruby title="pinyin above each Chinese word (needs zh.words.json)">Pinyin above words</button>
                <button class="btn on" data-tones title="each pinyin syllable in its tone's colour: 1 red · 2 orange · 3 green · 4 blue · light grey">Tone colours</button>
                <button class="btn" data-raise title="lift the lines above Chinese that is burned into the picture">Raise above burned-in text</button>
                <label class="check"><input type="checkbox" data-bg checked> dark box</label>
              </div>
              <div class="row">
                <button class="btn" data-cover title="hide subtitles that are part of the picture behind a blurred band (C)">Cover burned-in text</button>
                <span class="row" data-coverctl hidden>
                  <label class="check">from bottom <input type="range" data-cb min="0" max="70" step=".5" value="5"></label>
                  <label class="check">height <input type="range" data-ch min="4" max="60" step=".5" value="25"></label>
                </span>
              </div>
            </div></details>
            <details class="dd" data-dd><summary>Playback</summary><div class="ddp">
              <div class="row"><button class="btn" data-prev>◀ line</button><button class="btn" data-replay>↺ replay</button><button class="btn" data-next>line ▶</button></div>
              <div class="row">
                <button class="btn" data-loop title="repeat the current line (L)">loop line</button>
                <button class="btn" data-autopause title="pause at the end of every line, for shadowing (P)">pause after line</button>
              </div>
              <div class="row">
                <label class="check">Speed <select data-speed><option>0.5</option><option>0.75</option><option selected>1</option><option>1.25</option><option>1.5</option></select></label>
                <label class="check">Delay <input class="field" style="width:66px;padding:4px 6px" type="number" data-delay step=".1" value="0"> s</label>
              </div>
            </div></details>
            <details class="dd" data-dd><summary>Grammar</summary><div class="ddp grammar">
              <div class="row"><button class="btn on" data-grammar title="colour the characters that set the time (G)">Colour tenses</button></div>
              <div class="legend">
                <div><b class="g past">了</b><span><b>Past</b> · verb + 了: done · verb + 过: done before · 没 + verb: didn't</span></div>
                <div><b class="g present">在</b><span><b>Present</b> · 在 / 正在 + verb: happening now · verb + 着: ongoing</span></div>
                <div><b class="g future">要</b><span><b>Future</b> · 将 + verb · 快要 … 了: about to</span></div>
                <div><b class="g maybe">会</b><span><b>Maybe future</b> · 会 + verb (or "can") · 要 + verb (or "want to")</span></div>
                <div><b class="g change">了</b><span><b>New situation</b> · 了 at the end, not after a verb</span></div>
                <div><b class="g time-past">昨天</b><span><b>Time words</b> · 昨天 past · 现在 now · 明天 future</span></div>
              </div>
              <p class="note">Golden rule: Chinese verbs never change. Time comes from these words, and the time word goes <b>before</b> the verb: 我明天去, not 我去明天.</p>
              <p class="muted" style="margin:0;font-size:12px">Click a coloured character in the subtitles to see its rule. Found by rules, not by a person: when it can't tell, it says "maybe".</p>
            </div></details>
            <span data-extra></span>
            <details class="dd" data-dd><summary>Resources</summary><div class="ddp">
              ${RESOURCES.map(([n, u, d]) => `<a class="res" href="${u}" target="_blank" rel="noopener"><b>${n}</b><small>${d}</small></a>`).join('')}
            </div></details>
            <span class="grow"></span>
            <details class="dd icon right" data-dd><summary title="keyboard shortcuts">?</summary><div class="ddp keys">
              <div><b>Space</b> play · <b>←</b><b>→</b> line · <b>R</b> replay</div>
              <div><b>L</b> loop · <b>P</b> pause after line · <b>C</b> cover band</div>
              <div><b>1</b>–<b>9</b> track on/off · <b>↑</b><b>↓</b> lift</div>
              <div><b>G</b> tense colours · <b>F</b> fullscreen${opts.keys || ''}</div>
            </div></details>
            <button class="ib" data-full title="fullscreen (F)">⛶</button>
          </div>
        </div>
        ${opts.list ? '' : '<div class="transcript" data-list><div class="empty">The transcript appears here. Click a line to jump to it.</div></div>'}
      </div>`;
    const q = s => root.querySelector(s);
    const stage = q('.stage'), v = q('video'), ov = q('.ov'), list = opts.list || q('[data-list]');
    let tracks = [], delay = 0, loopLine = false, autoPause = false, pausedFor = -1, shownKey = '', lowLift = 6;
    let words = null, align = null, ruby = false, pin = null, pinCue = -1, videoKey = '';
    let tones = true, grammar = true;              // tone colours in pinyin, tense colours in Chinese (both on by default)
    const COVERS = 'zh-player-cover-v1';             // { videoKey: { on, b, h } }: the band differs per video
    const SHOWN = 'zh-player-shown-v1';              // { videoKey: { zh: true, pinyin: false, … } }

    /* ---- word ↔ pinyin links ---- */
    function wordsAt(c) {                         // the zh.words.json entry for this cue's time, if any
      if (!words) return null;
      const mid = (c.s + c.e) / 2;
      let lo = 0, hi = words.length - 1, r = -1;
      while (lo <= hi) { const m = (lo + hi) >> 1; if (words[m].s <= mid) { r = m; lo = m + 1; } else hi = m - 1; }
      return r >= 0 && words[r].e > mid ? words[r] : null;
    }
    const flat = x => x.replace(/\s/g, '');
    // English ↔ Chinese: an English word links to the Chinese word whose dictionary meaning contains it
    const STOP = new Set('a an the to of be is are am was were been do does did have has had it its this that these those in on at for with by from as or and but not no so very sb sth one someone something oneself etc used up out get got make'.split(' '));
    const SHORT = new Set(['i', 'me', 'my', 'we', 'us', 'he', 'she', 'go', 'ok']);
    const stem = w => { w = w.toLowerCase(); return w.length > 4 ? w.replace(/ies$/, 'y').replace(/(ing|ed|es)$/, '').replace(/s$/, '') : w.replace(/s$/, ''); };
    const keyWords = g => new Set((g || '').replace(/\([^)]*\)/g, ' ').toLowerCase().split(/[^a-z]+/)
      .filter(x => x && !STOP.has(x) && (x.length > 2 || SHORT.has(x))).map(stem));
    function englishHTML(text, w, links) {
      // 1. the dictionary: an English word inside the Chinese word's meaning (precise)
      // 2. else the model's link (zh.align.json): English character span -> Chinese character span
      const keys = w.w.flatMap((line, L) => line.map((p, k) => p[2] ? [`${L}-${k}`, keyWords(p[2])] : null)).filter(Boolean);
      const spans = []; let at = 0;                // character span of every Chinese word, as zh.align.json counts them
      w.w.forEach((line, L) => line.forEach((p, k) => { spans.push([at, at + p[0].length, `${L}-${k}`]); at += p[0].length; }));
      const byModel = (a, b) => {
        const l = (links || []).find(([es, ee]) => es < b && ee > a); if (!l) return null;
        const hit = spans.find(([zs, ze]) => zs < l[3] && ze > l[2]); return hit && hit[2];
      };
      let out = '', last = 0;
      for (const m of text.matchAll(/[A-Za-z]+/g)) {   // apostrophes split: I'm -> I + m, let's -> let + s
        const tok = m[0], st = stem(tok);
        const key = STOP.has(tok.toLowerCase()) ? null : ((keys.find(([, ks]) => ks.has(st)) || [])[0] || byModel(m.index, m.index + tok.length));
        out += esc(text.slice(last, m.index)) + (key ? `<i class="w" data-w="${key}">${esc(tok)}</i>` : esc(tok));
        last = m.index + tok.length;
      }
      return (out + esc(text.slice(last))).replace(/\n/g, '<br>');
    }
    let shownWords = null;                            // the zh.words.json entry of the line on screen
    function glossFor(key) {                       // the word card: characters, pinyin, meaning, HSK level, measure words
      if (!shownWords || !key) return '';
      const [L, k] = key.split('-').map(Number), p = (shownWords.w[L] || [])[k];
      if (!p) return '';
      const hsk = p[3] ? ` <em class="hsk">HSK ${p[3] === 7 ? '7–9' : p[3]}</em>` : '';
      const cl = p[4] ? ` <em>measure word ${esc(p[4])}</em>` : '';
      return `${esc(p[0])} <b>${tones ? toned(p[1], p[0]) : esc(p[1])}</b> ${p[2] ? '— ' + esc(p[2]) : ''}${hsk}${cl}`;
    }
    function ruleFor(el) {                          // the grammar card for a coloured character
      const r = RULES[el.dataset.g]; if (!r) return '';
      const line = el.closest('.ln, .cue'), all = line ? [...line.querySelectorAll('.g')] : [el];
      const same = all.filter(x => x.dataset.g === el.dataset.g).map(x => x.textContent).join('');
      return `<b>${esc(same)}</b> ${r[0]} — ${esc(r[1])}`;
    }
    function lineHTML(tr, c, inList) {
      if (tr.role === 'en') { const w = wordsAt(c); return w ? englishHTML(c.text, w, align && align[c.i]).replace(/<br>/g, inList ? ' ' : '<br>') : esc(c.text).replace(/\n/g, inList ? ' ' : '<br>'); }
      const w = tr.role === 'zh' || tr.role === 'pinyin' ? wordsAt(c) : null;
      const same = w && flat(c.text) === flat(w.w.map(l => l.map(p => tr.role === 'zh' ? p[0] : p[1]).join('')).join(''));
      if (!same) return esc(c.text).replace(/\n/g, inList ? ' ' : '<br>');   // edited by hand since: show it plain
      const pyColour = (tracks.find(t => t.role === 'pinyin') || {}).colour || COLOUR.pinyin;
      const py = (p, zh) => tones ? toned(p, zh) : esc(p);
      return w.w.map((line, L) => {
        const marks = new Map(grammar && w.g ? (w.g[L] || []) : []);   // character index in the line -> tense tag
        let at = 0;
        return line.map(([zh, p, g], k) => {
          const han = /[一-鿿]/.test(zh), key = `${L}-${k}`, start = at;
          at += zh.length;
          if (tr.role === 'pinyin') return han ? `<i class="w" data-w="${key}">${py(p, zh)}</i>` : esc(p);
          if (!han) return esc(zh);
          const chars = [...zh].map((ch, n) => { const t = marks.get(start + n);
            return t ? `<b class="g ${t.split(':')[0]}" data-g="${t}">${esc(ch)}</b>` : esc(ch); }).join('');
          const tip = inList && g ? ` title="${esc(p)} — ${esc(g)}"` : '';
          return ruby && !inList ? `<ruby class="w" data-w="${key}">${chars}<rt style="color:${pyColour}">${py(p, zh)}</rt></ruby>`
                                 : `<i class="w" data-w="${key}"${tip}>${chars}</i>`;
        }).join(tr.role === 'pinyin' ? ' ' : '').replace(/ ([,.!?:;)\]»"])/g, '$1');
      }).join(inList ? ' ' : '<br>');
    }
    function highlight(box, key) {
      box.querySelectorAll('.w.hl').forEach(e => e.classList.remove('hl'));
      if (key) box.querySelectorAll(`.w[data-w="${key}"]`).forEach(e => e.classList.add('hl'));
      const gl = box.querySelector(':scope > .gl');
      if (gl) { const html = glossFor(key); gl.innerHTML = html ? `<span>${html}</span>` : ''; }
    }

    /* ---- on screen ---- */
    const lead = () => tracks.find(t => t.on) || tracks[0];
    function tick(force) {
      const t = v.currentTime - delay, shown = [];
      let key = v.paused ? 'p' : 'r';
      tracks.forEach((tr, i) => { if (!tr.on) return; const k = cueAt(tr.cues, t); key += i + ':' + k + ';'; if (k >= 0) shown.push([tr, tr.cues[k]]); });
      const L = lead(), li = L ? cueAt(L.cues, t) : -1;
      key += 'L' + li;
      if (li >= 0 && !v.paused && t >= L.cues[li].e - 0.08) {
        if (loopLine) v.currentTime = L.cues[li].s + delay;
        else if (autoPause && pausedFor !== li) { pausedFor = li; v.pause(); }
      }
      if (!force && key === shownKey) return;
      shownKey = key;
      if (pin && li !== pinCue) pin = null;          // a pinned word lasts until its line ends
      shownWords = L && li >= 0 ? wordsAt(L.cues[li]) : null;
      ov.innerHTML = '<div class="gl"></div>' + shown.map(([tr, c]) =>
        `<div class="ln"><span class="${tr.blur && !v.paused ? 'blur' : ''}" style="color:${tr.colour};font-size:calc(var(--size) * ${tr.scale} * 1cqh)">` +
        `${lineHTML(tr, c)}</span></div>`).join('');
      if (pin && pin.startsWith('rule:')) { const el = ov.querySelector(`.g[data-g="${pin.slice(5)}"]`); if (el) showRule(el); }
      else if (pin) highlight(ov, pin);
      list.querySelectorAll('.cue.now').forEach(e => e.classList.remove('now'));
      const el = li >= 0 && list.children[li];
      if (el && el.classList.contains('cue')) {
        el.classList.add('now');
        const r = el.getBoundingClientRect(), b = list.getBoundingClientRect();
        if (r.top < b.top || r.bottom > b.bottom) list.scrollTop += r.top - b.top - b.height / 3;
      }
    }
    (function frame() { if (root.isConnected) { tick(false); requestAnimationFrame(frame); } })();
    const timer = setInterval(() => root.isConnected ? tick(false) : clearInterval(timer), 120);   // rAF sleeps in background tabs
    ['timeupdate', 'seeked', 'play', 'pause'].forEach(ev => v.addEventListener(ev, () => tick(false)));
    v.addEventListener('seeked', () => { pausedFor = -1; });

    /* ---- transcript and track list ---- */
    function renderList() {
      const L = lead();
      if (!L) { list.innerHTML = '<div class="empty">The transcript appears here. Click a line to jump to it.</div>'; return; }
      const fmt = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
      list.innerHTML = L.cues.map((c, i) => `<div class="cue" data-i="${i}"><div class="t">${fmt(c.s)}</div>` +
        tracks.filter(t => t.on).map(t => { const k = cueAt(t.cues, (c.s + c.e) / 2);
          return k >= 0 ? `<div class="l ${t.role}">${lineHTML(t, t.cues[k], true)}</div>` : ''; }).join('') +   // colours: kit.css, per theme
        '</div>').join('');
      shownKey = '';
    }
    function renderTracks() {
      q('[data-tracks]').innerHTML = tracks.length ? tracks.map((t, i) => `<div class="trk">
          <input type="checkbox" data-on="${i}" ${t.on ? 'checked' : ''} title="show / hide (key ${i + 1})">
          <input type="color" data-colour="${i}" value="${t.colour}" title="colour">
          <span class="nm" title="${esc(t.name)}">${esc(t.name)} <small>${LABEL[t.role]} · ${t.cues.length}</small></span>
          <input type="range" data-scale="${i}" min=".4" max="2" step=".05" value="${t.scale}" title="size of this track">
          <button class="mini ${t.blur ? 'on' : ''}" data-blur="${i}" title="blur while playing; shows when paused">blur</button>
          <span><button data-up="${i}" title="move up">▲</button><button data-dn="${i}" title="move down">▼</button></span></div>`).join('')
        : '<span class="muted">No subtitles loaded.</span>';
      const roles = new Set(tracks.map(t => t.role)), P = [['All', () => true]];
      if (roles.has('pinyin') && roles.has('en')) P.push(['Pinyin + English', r => r === 'pinyin' || r === 'en']);
      if (roles.has('zh') && roles.has('pinyin')) P.push(['中文 + Pinyin', r => r === 'zh' || r === 'pinyin']);
      for (const r of ['zh', 'pinyin', 'en']) if (roles.has(r)) P.push([LABEL[r] + ' only', x => x === r]);
      P.push(['None', () => false]);
      const box = q('[data-presets]');
      box.innerHTML = P.map(([n], i) => `<button class="btn" data-p="${i}">${n}</button>`).join('');
      box.onclick = e => { const b = e.target.closest('[data-p]'); if (!b) return;
        tracks.forEach(t => t.on = t.role !== 'stacked' && P[+b.dataset.p][1](t.role)); changed(); };
    }
    function changed(keepList) { save(); renderTracks(); if (!keepList) renderList(); tick(true); }
    const tbox = q('[data-tracks]');
    tbox.addEventListener('click', e => {
      const b = e.target.closest('[data-up],[data-dn],[data-blur]');
      if (b && 'up' in b.dataset) { const i = +b.dataset.up; if (i > 0) [tracks[i - 1], tracks[i]] = [tracks[i], tracks[i - 1]]; changed(); }
      else if (b && 'dn' in b.dataset) { const i = +b.dataset.dn; if (i < tracks.length - 1) [tracks[i + 1], tracks[i]] = [tracks[i], tracks[i + 1]]; changed(); }
      else if (b && 'blur' in b.dataset) { const t = tracks[+b.dataset.blur]; t.blur = !t.blur; changed(true); }
    });
    tbox.addEventListener('change', e => {
      if ('on' in e.target.dataset) { tracks[+e.target.dataset.on].on = e.target.checked; changed(); }
    });
    tbox.addEventListener('input', e => {        // live while dragging; the list is not rebuilt so the slider keeps focus
      if ('scale' in e.target.dataset) { tracks[+e.target.dataset.scale].scale = +e.target.value; save(); tick(true); }
      if ('colour' in e.target.dataset) { tracks[+e.target.dataset.colour].colour = e.target.value; save(); tick(true); }
    });
    function showRule(el) {                         // a tense mark explains itself in the card above the lines
      ov.querySelectorAll('.w.hl').forEach(x => x.classList.remove('hl'));
      const gl = ov.querySelector(':scope > .gl'); if (gl) gl.innerHTML = `<span class="rule ${el.dataset.g.split(':')[0]}">${ruleFor(el)}</span>`;
    }
    ov.addEventListener('mouseover', e => {
      const m = e.target.closest('.g'); if (m && !pin) return showRule(m);
      const w = e.target.closest('.w'); if (w && !pin) highlight(ov, w.dataset.w);
    });
    ov.addEventListener('mouseout', e => { if (e.target.closest('.w, .g') && !pin) highlight(ov, null); });
    ov.addEventListener('click', e => {             // click a word: pin it (and pause) so you can read it
      const m = e.target.closest('.g');
      if (m) { e.stopPropagation(); pin = 'rule:' + m.dataset.g; pinCue = lead() ? cueAt(lead().cues, v.currentTime - delay) : -1; showRule(m); v.pause(); return; }
      const w = e.target.closest('.w'); if (!w) return;
      e.stopPropagation();
      const L = lead();
      pin = pin === w.dataset.w ? null : w.dataset.w;
      pinCue = L ? cueAt(L.cues, v.currentTime - delay) : -1;
      highlight(ov, pin);
      if (pin) v.pause();
    });
    list.addEventListener('mouseover', e => { const w = e.target.closest('.w'), cue = e.target.closest('.cue'); if (cue) highlight(cue, w && w.dataset.w); });
    list.addEventListener('mouseleave', () => list.querySelectorAll('.w.hl').forEach(e => e.classList.remove('hl')));
    list.addEventListener('click', e => { const el = e.target.closest('.cue'), L = lead();
      if (el && L) { v.currentTime = L.cues[+el.dataset.i].s + delay + 0.01; v.play(); } });

    /* ---- controls ---- */
    const setVar = (n, val) => stage.style.setProperty('--' + n, val);
    const lift = q('[data-lift]'), size = q('[data-size]');
    size.oninput = () => { setVar('size', size.value); save(); };
    lift.oninput = () => { setVar('lift', lift.value); q('[data-raise]').classList.toggle('on', +lift.value > 12); save(); };
    q('[data-raise]').onclick = () => { const up = +lift.value > 12; if (!up) lowLift = +lift.value; lift.value = up ? lowLift : 17; lift.oninput(); };
    q('[data-bg]').onchange = e => { ov.classList.toggle('bg', e.target.checked); save(); };
    q('[data-ruby]').onclick = e => { ruby = !ruby; e.currentTarget.classList.toggle('on', ruby); save(); tick(true); };
    q('[data-tones]').onclick = e => { tones = !tones; e.currentTarget.classList.toggle('on', tones); save(); renderList(); tick(true); };
    q('[data-grammar]').onclick = e => { grammar = !grammar; e.currentTarget.classList.toggle('on', grammar); save(); renderList(); tick(true); };

    /* ---- cover band over burned-in subtitles (per video) ---- */
    const cover = q('.cover'), cb = q('[data-cb]'), ch = q('[data-ch]');
    const covers = () => { try { return JSON.parse(localStorage.getItem(COVERS)) || {}; } catch { return {}; } };
    function paintCover(on) {
      cover.hidden = !on; q('[data-coverctl]').hidden = !on; q('[data-cover]').classList.toggle('on', on);
      stage.style.setProperty('--cb', cb.value); stage.style.setProperty('--ch', ch.value);
    }
    function saveCover() {
      if (!videoKey) return;
      const all = covers(); all[videoKey] = { on: !cover.hidden, b: +cb.value, h: +ch.value };
      try { localStorage.setItem(COVERS, JSON.stringify(all)); } catch {}
    }
    q('[data-cover]').onclick = () => { paintCover(cover.hidden); saveCover(); };
    cb.oninput = ch.oninput = () => { paintCover(true); saveCover(); };
    q('[data-delay]').onchange = e => { delay = parseFloat(e.target.value) || 0; tick(true); };
    q('[data-speed]').onchange = e => { v.playbackRate = +e.target.value; save(); };
    function jump(dir) {
      const L = lead(); if (!L) return;
      const t = v.currentTime - delay; let i = cueAt(L.cues, t);
      if (i < 0) i = dir > 0 ? L.cues.findIndex(c => c.s > t) : Math.max(0, L.cues.findLastIndex(c => c.s <= t));
      else i += dir;
      if (i < 0) i = L.cues.length - 1;
      i = Math.max(0, Math.min(L.cues.length - 1, i));
      pausedFor = -1;
      v.currentTime = L.cues[i].s + delay + 0.01;
    }
    const toggle = (name, btn) => { const on = !btn.classList.contains('on'); btn.classList.toggle('on', on); return on; };
    q('[data-loop]').onclick = e => { loopLine = toggle('loop', e.currentTarget); };
    q('[data-autopause]').onclick = e => { autoPause = toggle('pause', e.currentTarget); pausedFor = -1; };
    q('[data-prev]').onclick = () => jump(-1); q('[data-next]').onclick = () => jump(1);
    q('[data-replay]').onclick = () => { jump(0); v.play(); };
    /* ---- fullscreen and the on-video control bar (the same in and out of fullscreen) ---- */
    const fullscreen = () => {
      if (document.fullscreenElement || document.webkitFullscreenElement) (document.exitFullscreen || document.webkitExitFullscreen).call(document);
      else (stage.requestFullscreen || stage.webkitRequestFullscreen).call(stage);
    };
    q('[data-full]').onclick = fullscreen;
    /* ---- the dropdowns: one open at a time; outside click or Esc closes ---- */
    const dds = () => root.querySelectorAll('details.dd[open]');
    root.addEventListener('toggle', e => {
      if (!e.target.matches('details.dd') || !e.target.open) return;
      dds().forEach(d => { if (d !== e.target) d.open = false; });
      // open downwards so the video and its subtitles stay visible; upwards only when there is no room
      const panel = e.target.querySelector('.ddp'), r = e.target.getBoundingClientRect();
      const below = innerHeight - r.bottom - 14, above = r.top - 14, up = below < 220 && above > below;
      panel.classList.toggle('up', up);
      panel.style.maxHeight = Math.max(160, up ? above : below) + 'px';
    }, true);
    document.addEventListener('click', e => { if (!e.target.closest('details.dd')) dds().forEach(d => d.open = false); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') dds().forEach(d => d.open = false); });
    q('[data-vfull]').onclick = fullscreen;
    const playPause = () => v.paused ? v.play() : v.pause();
    q('[data-play]').onclick = playPause;
    q('[data-vprev]').onclick = () => jump(-1); q('[data-vnext]').onclick = () => jump(1);
    const SPEEDS = ['0.5', '0.75', '1', '1.25', '1.5'], sel = q('[data-speed]');
    q('[data-vspeed]').onclick = () => { sel.value = SPEEDS[(SPEEDS.indexOf(sel.value) + 1) % SPEEDS.length]; sel.onchange({ target: sel }); };
    const fmt = t => isFinite(t) ? `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}` : '0:00';
    const seek = q('[data-seek]');
    let seeking = false;
    seek.oninput = () => { seeking = true; if (v.duration) v.currentTime = seek.value / 1000 * v.duration; };
    seek.onchange = () => { seeking = false; };
    const paintBar = () => {
      q('[data-play]').textContent = v.paused ? '▶' : '❚❚';
      q('[data-time]').textContent = `${fmt(v.currentTime)} / ${fmt(v.duration)}`;
      if (!seeking && v.duration) seek.value = Math.round(v.currentTime / v.duration * 1000);
      q('[data-vspeed]').textContent = (+sel.value) + '×';
    };
    ['timeupdate', 'play', 'pause', 'loadedmetadata', 'ratechange', 'seeked'].forEach(ev => v.addEventListener(ev, paintBar));
    let idle;                                    // hide the bar while playing and the mouse is still
    const wake = () => { stage.classList.add('awake'); clearTimeout(idle); idle = setTimeout(() => { if (!v.paused) stage.classList.remove('awake'); }, 2500); };
    stage.addEventListener('mousemove', wake); v.addEventListener('pause', wake); v.addEventListener('play', wake);
    let clickTimer;                              // single click = play/pause, double click = fullscreen
    v.onclick = () => { clearTimeout(clickTimer); clickTimer = setTimeout(playPause, 220); };
    v.ondblclick = () => { clearTimeout(clickTimer); fullscreen(); };
    document.addEventListener('keydown', e => {
      if (!root.isConnected || !stage.classList.contains('loaded') || /INPUT|SELECT|TEXTAREA/.test(e.target.tagName) || e.metaKey || e.ctrlKey) return;
      const k = e.key;
      if (k === ' ') { e.preventDefault(); v.paused ? v.play() : v.pause(); }
      else if (k === 'ArrowLeft') { e.preventDefault(); jump(-1); }
      else if (k === 'ArrowRight') { e.preventDefault(); jump(1); }
      else if (k === 'ArrowUp' || k === 'ArrowDown') { e.preventDefault(); lift.value = Math.max(0, Math.min(40, +lift.value + (k === 'ArrowUp' ? 1 : -1))); lift.oninput(); }
      else if (k === 'r' || k === 'R') { jump(0); v.play(); }
      else if (k === 'l' || k === 'L') q('[data-loop]').click();
      else if (k === 'p' || k === 'P') q('[data-autopause]').click();
      else if (k === 'f' || k === 'F') fullscreen();
      else if (k === 'c' || k === 'C') q('[data-cover]').click();
      else if (k === 'g' || k === 'G') q('[data-grammar]').click();
      else if (/^[1-9]$/.test(k) && tracks[+k - 1]) { tracks[+k - 1].on = !tracks[+k - 1].on; changed(); }
    });

    /* ---- remembered settings: global ones, plus one set per kind of line ---- */
    function save() {
      try {
        const roles = {};
        for (const t of tracks) if (t.role !== 'stacked' && !roles[t.role]) roles[t.role] = { scale: t.scale, colour: t.colour, blur: t.blur };
        localStorage.setItem(PREFS, JSON.stringify({ size: size.value, lift: lift.value, bg: q('[data-bg]').checked, speed: q('[data-speed]').value, ruby, tones, grammar, roles }));
        if (videoKey) {
          const shown = JSON.parse(localStorage.getItem(SHOWN) || '{}');
          shown[videoKey] = Object.fromEntries(tracks.filter(t => t.role !== 'stacked').map(t => [t.role, t.on]));
          localStorage.setItem(SHOWN, JSON.stringify(shown));
        }
      } catch {}
    }
    function restore() {
      let p = {}; try { p = JSON.parse(localStorage.getItem(PREFS)) || {}; } catch {}
      if (p.size) { size.value = p.size; setVar('size', p.size); }
      if (p.lift) { lift.value = p.lift; setVar('lift', p.lift); q('[data-raise]').classList.toggle('on', +p.lift > 12); }
      if (p.bg !== undefined) { q('[data-bg]').checked = p.bg; ov.classList.toggle('bg', p.bg); }
      if (p.speed) { q('[data-speed]').value = p.speed; v.playbackRate = +p.speed; }
      if (p.ruby !== undefined) { ruby = p.ruby; q('[data-ruby]').classList.toggle('on', ruby); }
      if (p.tones !== undefined) { tones = p.tones; q('[data-tones]').classList.toggle('on', tones); }
      if (p.grammar !== undefined) { grammar = p.grammar; q('[data-grammar]').classList.toggle('on', grammar); }
      for (const t of tracks) { const { on, ...look } = (p.roles || {})[t.role] || {}; Object.assign(t, look); }   // on/off is per video, below
      let shown = {}; try { shown = (JSON.parse(localStorage.getItem(SHOWN)) || {})[videoKey] || {}; } catch {}
      for (const t of tracks) if (t.role in shown) t.on = shown[t.role];     // this video's own choice wins
    }

    /* ---- public ---- */
    function load({ video, subs = [], words: w, align: al, append = false, id, cover: coverDefault = false }) {
      if (al !== undefined || !append) align = al && Array.isArray(al.cues) ? al.cues : null;
      if (id !== undefined) {
        videoKey = String(id);
        const c = covers()[videoKey];
        if (c) { cb.value = c.b; ch.value = c.h; }
        paintCover(c ? c.on : !!coverDefault);
      }
      if (w !== undefined || !append) { words = w && Array.isArray(w.cues) ? w.cues : null; pin = null; }
      if (video) {
        v.src = typeof video === 'string' ? video : URL.createObjectURL(video);
        stage.classList.add('loaded');
        v.playbackRate = +q('[data-speed]').value;
      }
      const added = subs.map(s => ({ name: s.name, role: roleOf(s.name), cues: parse(s.text).map((c, i) => ({ ...c, i })) }))
        .filter(t => t.cues.length)
        .map(t => ({ ...t, on: t.role !== 'stacked', scale: SCALE[t.role], colour: COLOUR[t.role], blur: false }));
      tracks = (append ? tracks.concat(added) : added).sort((a, b) => ORDER[a.role] - ORDER[b.role]);
      restore(); renderTracks(); renderList(); tick(true);
    }
    return { load, stage, video: v, extra: q('[data-extra]'), get tracks() { return tracks; } };
  }

  window.SubPlayer = { mount, parse, roleOf };
})();
