/* One self-made demo item, using its saved dictionary, word links and timings. */
(() => {
  const base = 'demo/library/pianpian-day/';
  const start = 22.48, end = 25.64;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const dictionary = document.getElementById('pp-dictionary');
  if (!dictionary) return;
  const wordButtons = [...dictionary.querySelectorAll('[data-pp-word]')];
  const dictionaryStatus = dictionary.querySelector('[data-pp-dictionary-status]');
  const previews = [...document.querySelectorAll('[data-pp-preview]')];
  const english = previews[0].querySelector('[data-pp-en]').textContent;
  let links = [];
  let cue = null;

  function renderTone(target, pinyin, chinese) {
    target.replaceChildren();
    for (const [text, tone] of SubPlayer.toneSegments(pinyin, chinese).pinyin) {
      const span = document.createElement('span');
      if (tone) span.className = `t${tone}`;
      span.textContent = text;
      target.append(span);
    }
  }

  function selectPreview(root, index) {
    root.querySelectorAll('[data-pp-linked]').forEach(button => {
      const selected = Number(button.dataset.ppLinked) === index;
      button.classList.toggle('hl', selected);
      button.setAttribute('aria-pressed', selected);
    });
    const word = cue.w[0][index];
    root.querySelector('[data-pp-selection]').textContent = `${word[0]} — ${word[2]}`;
  }

  function renderPreviews() {
    if (!cue) return;
    const words = cue.w[0];
    let position = 0;
    const ranges = words.map(word => { const from = position; position += word[0].length; return [from, position]; });
    function wordButton(index, text) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'w';
      button.dataset.ppLinked = index;
      button.dataset.ppSpoken = index;
      button.textContent = text;
      return button;
    }
    for (const root of previews) {
      const selected = Number(root.querySelector('[aria-pressed="true"]')?.dataset.ppLinked ?? 3);
      const zh = root.querySelector('[data-pp-zh]'), py = root.querySelector('[data-pp-py]'), en = root.querySelector('[data-pp-en]');
      zh.replaceChildren(); py.replaceChildren(); en.replaceChildren();
      words.forEach((word, index) => {
        if (!word[2]) { zh.append(word[0]); py.append(word[1]); return; }
        zh.append(wordButton(index, word[0]));
        if (index) py.append(' ');
        const pinyin = wordButton(index, '');
        renderTone(pinyin, word[1], word[0]);
        py.append(pinyin);
      });
      let last = 0;
      for (const [from, to, zs, ze] of links) {
        const index = ranges.findIndex(([a, b]) => a < ze && b > zs);
        en.append(english.slice(last, from));
        en.append(index < 0 ? english.slice(from, to) : wordButton(index, english.slice(from, to)));
        last = to;
      }
      en.append(english.slice(last));
      selectPreview(root, selected);
    }
  }
  previews.forEach(root => root.addEventListener('click', event => {
    const button = event.target.closest('[data-pp-linked]');
    if (button) selectPreview(root, Number(button.dataset.ppLinked));
  }));

  function selectWord(index) {
    const word = cue.w[0][index];
    wordButtons.forEach((button, i) => button.setAttribute('aria-pressed', i === index));
    dictionary.querySelector('[data-pp-gloss-word]').textContent = word[0];
    const pinyin = dictionary.querySelector('[data-pp-pinyin]');
    pinyin.className = 'pp-pinyin';
    renderTone(pinyin, word[1], word[0]);
    dictionary.querySelector('[data-pp-meaning]').textContent = word[2];
  }
  wordButtons.forEach((button, index) => {
    button.disabled = true;
    button.addEventListener('click', () => selectWord(index));
  });
  fetch(base + 'zh.words.json').then(response => {
    if (!response.ok) throw new Error('Dictionary unavailable');
    return response.json();
  }).then(data => {
    cue = data.cues.find(item => item.s === start && item.e === end);
    if (!cue || !cue.w?.[0]?.[3]) throw new Error('Demo line unavailable');
    wordButtons.forEach(button => { button.disabled = false; });
    document.querySelectorAll('[data-pp-role-pinyin]').forEach(target => {
      const word = cue.w[0][Number(target.dataset.ppRolePinyin)];
      renderTone(target, word[1], word[0]);
    });
    renderPreviews();
  }).catch(() => {
    cue = null;
    dictionaryStatus.textContent = 'Dictionary could not load. Reload to try again.';
  });
  fetch(base + 'zh.align.json').then(response => {
    if (!response.ok) throw new Error('Word links unavailable');
    return response.json();
  }).then(data => {
    links = data.cues[5];
    renderPreviews();
  }).catch(() => {
    links = [];
    previews.forEach(root => { root.querySelector('[data-pp-selection]').textContent = 'English word links could not load.'; });
  });

  const grammar = document.getElementById('pp-grammar');
  const roles = [
    ['我 · who acts', '我 means “I”: the person doing the learning.'],
    ['正在 · action in progress', '正在 before 学 says the learning is in progress. It does not mark past or future by itself.'],
    ['学 · the action', '学 means “learn” or “study”. 中文 tells you what is being learned.'],
    ['中文 · what is learned', '中文 means “Chinese language”. Here it is the object of 学.'],
  ];
  const roleButtons = [...grammar.querySelectorAll('[data-pp-role]')];
  roleButtons.forEach((button, index) => button.addEventListener('click', () => {
    roleButtons.forEach((item, i) => item.setAttribute('aria-pressed', i === index));
    grammar.querySelector('[data-pp-role-title]').textContent = roles[index][0];
    grammar.querySelector('[data-pp-role-text]').textContent = roles[index][1];
  }));
  const replay = document.getElementById('pp-replay');
  const audio = replay.querySelector('audio');
  const play = replay.querySelector('[data-pp-play]');
  const loop = replay.querySelector('[data-pp-loop]');
  const slow = replay.querySelector('[data-pp-slow]');
  const audioStatus = replay.querySelector('[data-pp-audio-status]');
  const playhead = replay.querySelector('[data-pp-playhead]');
  let looping = false, frame = 0;

  function paintAudio() {
    const time = audio.currentTime;
    if (!reduced.matches || audio.paused) playhead.setAttribute('cx', 24 + 272 * Math.max(0, Math.min(1, (time - start) / (end - start))));
    replay.querySelectorAll('[data-pp-spoken]').forEach(word => {
      const timing = cue?.k?.[0]?.[Number(word.dataset.ppSpoken)];
      const speaking = !audio.paused && !!timing && time >= timing[0] && time < timing[1];
      word.classList.toggle('pp-speaking', speaking);
      word.classList.toggle('say', speaking);
    });
  }
  function tick() {
    if (audio.currentTime >= end) {
      if (looping) audio.currentTime = start;
      else {
        audio.pause();
        audio.currentTime = end;
      }
    }
    paintAudio();
    if (!audio.paused) frame = requestAnimationFrame(tick);
  }
  function labelPlay(label) {
    play.setAttribute('aria-label', label);
    play.title = label;
    play.querySelector('[data-pp-play-icon]').setAttribute('d', label === 'Pause' ? 'M8 5v14M16 5v14' : 'm8 5 11 7-11 7Z');
  }
  play.addEventListener('click', async () => {
    if (!audio.paused) { audio.pause(); return; }
    try {
      if (audio.currentTime < start || audio.currentTime >= end) audio.currentTime = start;
      await audio.play();
    } catch (error) {
      if (error.name === 'AbortError') return;
      audioStatus.textContent = 'Audio could not play. Try Play line again.';
      labelPlay('Play line');
    }
  });
  audio.addEventListener('play', () => {
    labelPlay('Pause');
    audioStatus.textContent = cue ? 'Estimated word timings.' : 'Word timings unavailable.';
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(tick);
  });
  audio.addEventListener('pause', () => {
    cancelAnimationFrame(frame);
    const finished = audio.currentTime >= end;
    labelPlay(finished ? 'Replay line' : 'Resume');
    audioStatus.textContent = finished ? 'Line finished.' : 'Paused.';
    paintAudio();
  });
  audio.addEventListener('error', () => {
    audio.pause();
    audioStatus.textContent = 'Audio could not load. Reload to try again.';
    labelPlay('Play line');
  });
  loop.addEventListener('click', () => {
    looping = !looping;
    loop.setAttribute('aria-pressed', looping);
  });
  slow.addEventListener('click', () => {
    const active = slow.getAttribute('aria-pressed') !== 'true';
    slow.setAttribute('aria-pressed', active);
    audio.playbackRate = active ? 0.75 : 1;
    slow.querySelector('[data-pp-speed]').textContent = `${audio.playbackRate}×`;
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden) audio.pause(); });
})();
