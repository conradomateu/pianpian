/* Direct Anki export. The page owns the API and source; the player owns selection. */
window.AnkiExport = (() => {
  function mount(player, { api, source, enabled }) {
    const menu = document.createElement('details');
    menu.className = 'dd icon anki';
    menu.innerHTML = `
      <summary aria-label="Prepare Anki card" title="Prepare Anki card"><img src="assets/anki-logo.png" alt="" width="20" height="20"></summary>
      <div class="ddp anki-panel" role="region" aria-label="Prepare Anki card">
        <header class="anki-header">
          <button class="btn anki-close" data-anki-close aria-label="Close Anki card" title="Close Anki card">×</button>
          <p class="anki-expression" data-anki-expression-preview lang="zh"></p>
          <p class="anki-help" data-anki-pinyin-preview></p>
          <p data-anki-meaning-preview></p>
          <p class="anki-context" data-anki-sentence-preview lang="zh"></p>
          <p class="anki-help" data-anki-help>Click a Chinese word, then Shift+click another to select a range.</p>
        </header>
        <div class="anki-scroll">
          <fieldset data-anki-draft hidden>
            <div class="row anki-listen"><button class="btn" data-anki-preview>Listen</button><span class="anki-help" data-anki-duration></span></div>
            <audio data-anki-audio controls preload="none" hidden></audio>
            <p class="anki-help" data-anki-preview-help>Listen before adding the note.</p>
            <details class="anki-fold" data-anki-adjust>
              <summary>Adjust audio</summary>
              <div class="anki-pair">
                <label>Start (seconds)<input class="field" data-anki-start type="number" min="0" step="0.001"></label>
                <label>End (seconds)<input class="field" data-anki-end type="number" min="0" step="0.001"></label>
                <div class="anki-steps"><button class="btn" data-anki-start-minus aria-label="Start 100 ms earlier">−100 ms</button><button class="btn" data-anki-start-plus aria-label="Start 100 ms later">+100 ms</button></div>
                <div class="anki-steps"><button class="btn" data-anki-end-minus aria-label="End 100 ms earlier">−100 ms</button><button class="btn" data-anki-end-plus aria-label="End 100 ms later">+100 ms</button></div>
              </div>
              <label class="check"><input data-anki-context type="checkbox">Use sentence audio</label>
              <p class="anki-help" data-anki-timing></p>
            </details>
            <details class="anki-fold" data-anki-edit>
              <summary>Edit text &amp; color</summary>
              <label>Chinese<input class="field" data-anki-expression lang="zh" autocomplete="off"></label>
              <label>Pinyin<input class="field" data-anki-pinyin autocomplete="off"></label>
              <label class="check"><input data-anki-tone-pinyin type="checkbox" checked>Pinyin tone colors</label>
              <label class="check"><input data-anki-tone-expression type="checkbox">Chinese tone colors</label>
              <label>Meaning<textarea class="field" data-anki-meaning rows="2"></textarea></label>
              <label>Sentence<textarea class="field" data-anki-sentence-text lang="zh" rows="2"></textarea></label>
              <label>Translation<textarea class="field" data-anki-translation rows="2"></textarea></label>
              <label>Highlight<select class="field" data-anki-highlight><option value="none">None</option><option value="jade" selected>Jade</option><option value="coral">Coral</option><option value="blue">Blue</option><option value="gold">Gold</option></select></label>
            </details>
          </fieldset>
          <details class="anki-fold anki-connection" data-anki-more>
            <summary>More options</summary>
            <button class="btn" data-anki-sentence>Use full sentence</button>
            <fieldset data-anki-margins>
              <div class="anki-pair">
                <label>Before (ms)<input class="field" data-anki-before type="number" min="0" step="10" value="150"></label>
                <label>After (ms)<input class="field" data-anki-after type="number" min="0" step="10" value="200"></label>
              </div>
            </fieldset>
            <fieldset data-anki-settings>
              <legend>Connection settings</legend>
              <p class="anki-help">Connects only to localhost on this computer.</p>
              <label>Port<input class="field" data-anki-port type="number" min="1" max="65535" step="1" value="8765"></label>
              <label>API key (optional)<input class="field" data-anki-key type="password" autocomplete="off" placeholder="Leave blank to keep the saved key"></label>
              <label class="check"><input data-anki-clear-key type="checkbox">Clear saved key</label>
              <button class="btn" data-anki-connect>Save connection</button>
            </fieldset>
          </details>
        </div>
        <footer class="anki-footer">
          <label>Deck<select class="field" data-anki-deck></select></label>
          <label data-anki-new-label hidden>New deck name<input class="field" data-anki-new autocomplete="off"></label>
          <div class="row"><button class="btn primary" data-anki-save>Add to Anki</button><button class="btn" data-anki-open hidden>Open in Anki</button></div>
          <div class="row anki-status"><p data-anki-status role="status" aria-live="polite"></p><button class="btn" data-anki-retry>Retry connection</button></div>
          <p class="anki-help" data-anki-setup hidden>Open Anki Desktop with <a href="https://ankiweb.net/shared/info/2055492159" target="_blank" rel="noopener noreferrer">AnkiConnect</a> (code <code>2055492159</code>), then restart Anki.</p>
          <p data-anki-result role="status" aria-live="polite"></p>
        </footer>
      </div>`;
    const toolbar = player.extra.parentElement;
    toolbar.insertBefore(menu, toolbar.querySelector('[data-full]'));
    const q = name => menu.querySelector(`[data-anki-${name}]`);
    const trigger = menu.querySelector(':scope > summary'), panel = menu.querySelector('.anki-panel');
    const fields = { expression: q('expression'), pinyin: q('pinyin'), meaning: q('meaning'), sentence: q('sentence-text'), translation: q('translation') };
    const available = !!enabled && location.protocol !== 'file:';
    let selection = null, connection = null, preview = null, note = null, dirty = false;
    let generation = 0, busy = false, settingsEdited = false, deckEdited = false;
    let anchor = trigger, playback = 0;
    const sourceId = () => source()?.id;
    const validSource = () => !!selection && !!sourceId() && selection.sourceId === sourceId() && Number.isFinite(player.video.duration);
    const interval = () => ({ start: q('start').valueAsNumber, end: q('end').valueAsNumber });
    const validInterval = () => {
      const { start, end } = interval();
      return validSource() && Number.isFinite(start) && Number.isFinite(end) && start >= 0 && end > start && end <= player.video.duration;
    };
    const deckName = () => q('deck').value === '' ? q('new').value.trim() : q('deck').value;
    function position() {
      if (!menu.open) return;
      const target = anchor?.isConnected && anchor.getClientRects().length ? anchor : trigger;
      const r = target.getBoundingClientRect(), gap = 8;
      const top = Math.max(gap, Math.min(innerHeight - gap, r.top));
      const bottom = Math.max(gap, Math.min(innerHeight - gap, r.bottom));
      const above = top - gap * 2, below = innerHeight - bottom - gap * 2;
      const up = below < 360 && above > below;
      const minimum = panel.querySelector('.anki-header').offsetHeight + panel.querySelector('.anki-footer').offsetHeight + 180;
      const height = Math.min(innerHeight - gap * 2, Math.max(minimum, up ? above : below));
      panel.classList.toggle('up', up);
      panel.style.maxHeight = Math.max(0, height) + 'px';
      panel.style.top = up ? 'auto' : Math.min(bottom + gap, innerHeight - height - gap) + 'px';
      panel.style.bottom = up ? Math.min(innerHeight - top + gap, innerHeight - height - gap) + 'px' : 'auto';
      panel.style.left = Math.max(gap, Math.min(r.left, innerWidth - panel.offsetWidth - gap)) + 'px';
    }
    function toneFields() {
      const expression = fields.expression.value.trim(), pinyin = fields.pinyin.value.trim();
      const paired = expression === selection?.expression.trim() && pinyin === selection?.pinyin.trim();
      const segments = SubPlayer.toneSegments(pinyin, paired ? expression : '');
      const tones = {};
      if (q('tone-pinyin').checked) tones.pinyin = segments.pinyin;
      if (q('tone-expression').checked) tones.expression = paired ? segments.expression : expression ? [[expression, 0]] : [];
      return tones;
    }
    function overview() {
      const expression = fields.expression.value.trim(), sentence = fields.sentence.value.trim(), tones = toneFields();
      panel.dataset.highlight = q('highlight').value;
      const colored = (segments, text) => (segments || [[text, 0]]).map(([text, tone]) => {
        if (!tone) return document.createTextNode(text);
        const span = document.createElement('span');
        span.className = `t${tone}`;
        span.textContent = text;
        return span;
      });
      const marked = () => {
        const mark = document.createElement('mark');
        mark.append(...colored(tones.expression, expression));
        return mark;
      };
      q('expression-preview').replaceChildren(marked());
      q('pinyin-preview').replaceChildren(...colored(tones.pinyin, fields.pinyin.value.trim()));
      q('meaning-preview').textContent = fields.meaning.value;
      const context = q('sentence-preview');
      context.replaceChildren();
      // Literal matches only; edited card text never becomes HTML or a regular expression.
      const parts = expression ? sentence.split(expression) : [sentence];
      parts.forEach((part, i) => { if (i) context.append(marked()); context.append(part); });
      [q('pinyin-preview'), q('meaning-preview'), context].forEach(el => { el.title = el.textContent; });
    }
    function controls() {
      q('settings').disabled = busy || !available;
      q('margins').disabled = busy || !available || !selection;
      q('retry').disabled = busy || !available;
      q('sentence').disabled = busy || !available || !sourceId() || !Number.isFinite(player.video.duration);
      q('draft').disabled = busy || !available;
      ['deck', 'new', 'open'].forEach(name => { q(name).disabled = busy || !available || !selection; });
      q('preview').disabled = busy || !available || !validInterval();
      q('save').disabled = busy || !available || !validInterval() || !preview || !fields.expression.value.trim() || !deckName() || (!!note && !dirty && note.state !== 'exists');
      q('save').textContent = note ? (note.state === 'exists' || dirty ? 'Update existing note' : note.state === 'added' ? 'Added' : 'Updated') : 'Add to Anki';
      q('open').hidden = !note;
      q('new-label').hidden = q('deck').value !== '';
      const { start, end } = interval();
      q('duration').textContent = validInterval() ? (end - start).toFixed(2) + ' s' : 'Choose a valid interval';
      menu.setAttribute('aria-busy', String(busy));
      position();
    }
    function invalidatePreview() {
      playback++;
      preview = null;
      q('audio').pause();
      q('audio').removeAttribute('src');
      q('audio').load();
      q('audio').hidden = true;
      q('preview-help').textContent = 'Listen before adding the note.';
    }
    function edited() {
      dirty = true;
      q('result').textContent = '';
      overview();
      controls();
    }
    function defaultInterval() {
      invalidatePreview();
      if (!selection) return;
      const before = q('before').valueAsNumber, after = q('after').valueAsNumber;
      const context = q('context').checked;
      const start = context ? selection.sentenceStart : selection.start;
      const end = context ? selection.sentenceEnd : selection.end;
      q('start').value = Number.isFinite(before) && before >= 0 ? Math.min(player.video.duration, Math.max(0, +(start - before / 1000).toFixed(3))) : '';
      q('end').value = Number.isFinite(after) && after >= 0 ? Math.max(0, Math.min(player.video.duration, +(end + after / 1000).toFixed(3))) : '';
      edited();
    }
    function reset() {
      generation++;
      busy = false;
      selection = note = null;
      dirty = false;
      invalidatePreview();
      Object.values(fields).forEach(input => { input.value = ''; });
      q('start').value = q('end').value = '';
      q('context').checked = false;
      q('highlight').value = 'jade';
      q('tone-pinyin').checked = true;
      q('tone-expression').checked = false;
      q('draft').hidden = true;
      q('help').hidden = false;
      q('result').textContent = '';
      overview();
      controls();
    }
    function selectionChanged(value) {
      const same = selection && value && ['sourceId', 'cueStart', 'cueEnd', 'first', 'last', 'sentence', 'expression']
        .every(key => selection[key] === value[key]);
      const timingChanged = !same || ['start', 'end', 'sentenceStart', 'sentenceEnd'].some(key => selection[key] !== value[key]);
      if (!same) {
        reset();
        if (!value) return;
        Object.entries(fields).forEach(([key, input]) => { input.value = value[key] || ''; });
      } else if (timingChanged) {
        generation++;
        busy = false;
      }
      selection = { ...value };
      q('draft').hidden = false;
      q('help').hidden = true;
      q('timing').textContent = value.timing === 'word'
        ? 'Word timing. Adjust the clip if needed.'
        : 'Word timing is unavailable. This clip uses sentence timing; adjust it by ear.';
      if (timingChanged) defaultInterval();
      else { overview(); controls(); }
    }
    function showStatus(status) {
      connection = { ...connection, ...status };
      q('status').textContent = status.message || (status.state === 'connected' ? 'Connected to Anki.' : 'Could not connect to Anki.');
      q('status').dataset.state = status.state;
      q('setup').hidden = status.state === 'connected';
      if (!settingsEdited) q('port').value = status.port || 8765;
      q('key').placeholder = status.hasKey ? 'Leave blank to keep the saved key' : 'No key saved';
      const previous = q('deck').value;
      const names = Array.isArray(status.decks) ? status.decks : [];
      // Keep the user's deck choice through connection failures and refreshes.
      if (status.state === 'connected') {
        q('deck').replaceChildren(...names.map(name => new Option(name, name)), new Option('New deck…', ''));
        const preferred = deckEdited ? previous : status.deck || previous;
        if (preferred === '' || names.includes(preferred)) q('deck').value = preferred;
      }
      controls();
    }
    async function run(action) {
      if (!available || busy) return;
      const token = ++generation, id = sourceId();
      const current = () => token === generation && id === sourceId();
      busy = true;
      q('result').textContent = '';
      controls();
      try { await action(current); }
      catch (err) {
        if (current()) {
          q('status').dataset.state = connection?.state === 'connected' ? '' : connection?.state || '';
          q('result').textContent = err.message || 'Could not complete the request. Your draft is kept.';
        }
      }
      finally { if (current()) { busy = false; controls(); } }
    }
    async function status(current, body) {
      let result;
      try { result = await api(body === undefined ? '/api/anki/status' : '/api/anki/settings', body); }
      catch (err) {
        if (current()) showStatus({ state: 'error', message: err.message || 'Could not connect to Anki.' });
        throw err;
      }
      if (!current()) return null;
      showStatus(result);
      return result;
    }
    const refresh = () => run(async current => {
      q('status').textContent = 'Checking Anki…';
      q('status').dataset.state = '';
      await status(current);
    });
    menu.addEventListener('toggle', e => {
      if (e.target !== menu) return;
      if (menu.open) {
        player.video.pause();
        position();
        refresh();
      } else {
        playback++;
        q('audio').pause();
      }
    });
    function open(target) {
      anchor = target || trigger;
      menu.open = true;
      player.video.pause();
      position();
    }
    trigger.addEventListener('click', () => { anchor = trigger; });
    q('close').onclick = () => { menu.open = false; q('audio').pause(); trigger.focus({ preventScroll: true }); };
    window.addEventListener('resize', position);
    document.addEventListener('scroll', position, true);
    new ResizeObserver(position).observe(panel);
    function fullscreenChanged() {
      const fullscreen = document.fullscreenElement || document.webkitFullscreenElement;
      const parent = fullscreen?.contains(player.video) ? fullscreen : toolbar;
      if (menu.parentElement !== parent) parent.insertBefore(menu, parent === toolbar ? toolbar.querySelector('[data-full]') : null);
      position();
    }
    document.addEventListener('fullscreenchange', fullscreenChanged);
    document.addEventListener('webkitfullscreenchange', fullscreenChanged);
    q('retry').onclick = refresh;
    q('settings').oninput = () => { settingsEdited = true; };
    q('connect').onclick = () => run(async current => {
      const port = q('port').valueAsNumber;
      if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Enter a port from 1 to 65535.');
      const body = { port };
      if (q('clear-key').checked) body.key = '';
      else if (q('key').value) body.key = q('key').value;
      await status(current, body);
      if (current()) { settingsEdited = false; q('key').value = ''; q('clear-key').checked = false; }
    });
    q('sentence').onclick = () => {
      player.selectAnkiSentence();
      if (!player.ankiSelection()) q('result').textContent = 'Seek to a Chinese subtitle, then choose Use full sentence.';
    };
    Object.values(fields).forEach(input => { input.oninput = edited; });
    q('highlight').onchange = edited;
    ['tone-pinyin', 'tone-expression'].forEach(name => { q(name).onchange = edited; });
    ['context', 'before', 'after'].forEach(name => { q(name).oninput = defaultInterval; });
    ['start', 'end'].forEach(name => {
      q(name).oninput = () => { invalidatePreview(); edited(); };
      ['minus', 'plus'].forEach(direction => {
        q(`${name}-${direction}`).onclick = () => {
          const value = q(name).valueAsNumber;
          if (!Number.isFinite(value)) return;
          q(name).value = Math.max(0, Math.min(player.video.duration, +(value + (direction === 'plus' ? .1 : -.1)).toFixed(3)));
          q(name).oninput();
        };
      });
    });
    q('deck').onchange = () => { deckEdited = true; edited(); };
    q('new').oninput = edited;
    const payload = () => ({
      id: sourceId(), selection: { cueStart: selection.cueStart, cueEnd: selection.cueEnd, first: selection.first, last: selection.last,
        sentence: selection.sentence, expression: selection.expression }, ...interval(),
    });
    async function listen(token) {
      if (!menu.open || token !== playback) return;
      player.video.pause();
      q('audio').currentTime = 0;
      try { await q('audio').play(); }
      catch (_) {
        if (menu.open && token === playback) q('preview-help').textContent = 'Preview ready. Press play in the audio controls to listen.';
      }
    }
    q('preview').onclick = () => {
      if (preview) { listen(playback); return; }
      run(async current => {
        if (!validInterval()) throw new Error('Choose a valid audio interval within this video.');
        invalidatePreview();
        const playToken = playback;
        q('result').textContent = 'Preparing audio…';
        const request = payload(), result = await api('/api/anki/preview', request);
        if (!current()) return;
        if (!result.url || !Number.isFinite(result.start) || !Number.isFinite(result.end) || result.start < 0 || result.end <= result.start ||
            result.end > player.video.duration || Math.abs(result.start - request.start) > .001 || Math.abs(result.end - request.end) > .05) throw new Error('The preview interval changed. Adjust the times and preview again.');
        // ffmpeg reports media duration to centiseconds; keep the exact returned clip for export.
        if (result.start !== request.start || result.end !== request.end) dirty = true;
        q('start').value = result.start;
        q('end').value = result.end;
        q('audio').src = result.url;
        q('audio').hidden = false;
        preview = result.url;
        q('preview-help').textContent = 'This exact interval will be added. Use the audio controls to review it.';
        q('result').textContent = '';
        await listen(playToken);
      });
    };
    q('audio').onerror = () => {
      if (!preview) return;
      invalidatePreview();
      q('result').textContent = 'Could not load the audio preview. Generate it again.';
      controls();
    };
    q('save').onclick = () => run(async current => {
      if (!validInterval() || !preview) throw new Error('Generate a preview for the current audio interval first.');
      const profile = note?.profile || connection?.profile, deck = deckName();
      const request = { ...payload(), deck, profile, preview, highlight: q('highlight').value, tones: toneFields(), update: !!note };
      Object.entries(fields).forEach(([key, input]) => { request[key] = input.value; });
      q('result').textContent = 'Checking Anki before saving…';
      const checked = await status(current);
      if (!checked) return;
      if (checked.state !== 'connected') throw new Error(checked.message || 'Open Anki and retry. Your draft is kept.');
      if (profile && checked.profile !== profile) {
        note = null;
        throw new Error('The Anki profile changed. Check the deck, then save again.');
      }
      request.profile = checked.profile;
      const result = await api('/api/anki/export', request);
      if (!current()) return;
      if (!['added', 'exists', 'updated'].includes(result.state) || !result.noteId) throw new Error('Anki did not confirm the note. Retry to check whether it exists.');
      note = { ...result, profile: checked.profile };
      dirty = false;
      if (result.deck && ![...q('deck').options].some(option => option.value === result.deck)) q('deck').add(new Option(result.deck, result.deck), 0);
      if (result.deck) { q('deck').value = result.deck; deckEdited = false; }
      q('result').textContent = result.state === 'exists' ? 'This selection already exists. Choose Update existing note to replace its content and keep its review history.' : result.state === 'added' ? 'Added to Anki.' : 'Updated in Anki. Review history kept.';
    });
    q('open').onclick = () => run(async current => {
      await api('/api/anki/open', { noteId: note.noteId, profile: note.profile });
      if (current()) q('result').textContent = 'Opened in Anki.';
    });
    player.video.addEventListener('durationchange', controls);
    if (!available) {
      q('status').textContent = 'Anki export is available in the local Pianpian app. Open the app and choose a library video.';
      q('setup').hidden = true;
      q('retry').hidden = true;
      q('settings').hidden = true;
    } else q('status').textContent = 'Open Anki Desktop to export a note.';
    controls();
    return { selectionChanged, reset, open };
  }
  return { mount };
})();
