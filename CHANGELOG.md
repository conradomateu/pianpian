# Changelog

## [0.2.0](https://github.com/conradomateu/pianpian/compare/pianpian-v0.1.4...pianpian-v0.2.0) (2026-11-07)


### Features

* add Anki export and interactive learning website ([f3205e2](https://github.com/conradomateu/pianpian/commit/f3205e2726bdcdd80d734a05da6e579a49bb3a0f))
* no primary download on a computer that can run neither build ([f6ef20a](https://github.com/conradomateu/pianpian/commit/f6ef20aa0463305d42342ff03184eb3aadc32850))
* one primary download button, for the visitor's platform ([b8e5b11](https://github.com/conradomateu/pianpian/commit/b8e5b11b70eb93f42067d040890055c42cd0bc21))
* phone layout for the website demo ([3d1c33e](https://github.com/conradomateu/pianpian/commit/3d1c33e92ace17dd702a1b821698d98fb831c3d0))
* space Chinese subtitle words 0.3em apart ([b7995f6](https://github.com/conradomateu/pianpian/commit/b7995f6ac896a6d7ce355b15c9168a81d03c4726))
* Windows download on the website, ordered for the visitor's computer ([618cc94](https://github.com/conradomateu/pianpian/commit/618cc9464a65939e1a856ba8707e6187ad04da32))
* Windows installer ([cdb44fc](https://github.com/conradomateu/pianpian/commit/cdb44fcc2fd8e209058d778c013ff78b4fab0fb4))


### Bug Fixes

* count bundled files once when reporting Mac app size ([c8b92a9](https://github.com/conradomateu/pianpian/commit/c8b92a9a5be3ac9a93e6df10cc1cc5b77dd0f5e2))
* escape the Windows paths in engine.py's docstrings ([6067397](https://github.com/conradomateu/pianpian/commit/606739735844abbadd771b69aa70445a640ef493))
* exclude setup from active Anki media operations ([2a0cec2](https://github.com/conradomateu/pianpian/commit/2a0cec273a193b1f6e6c54f6339cd0342a18bbbb))
* give every Windows job the GPU build the setup chose ([66cfeb8](https://github.com/conradomateu/pianpian/commit/66cfeb8e6a6b60c8e5da4db9488b797e26db9290))
* give pinyin words the same 0.3em gap as Chinese words ([18822a5](https://github.com/conradomateu/pianpian/commit/18822a55bac50ceae2a0869e35dd5056bd307e72))
* harden integrated app and platform downloads ([6f7cf51](https://github.com/conradomateu/pianpian/commit/6f7cf51506ffa23c1e6fc88eb51309823229137d))
* install on x64 Windows 10+ only, clear old app files on upgrade, one app at a time ([88bd07d](https://github.com/conradomateu/pianpian/commit/88bd07de0d463a1c7f67b6cbde9813d33275e918))
* integrate current main and close Windows review gaps ([0f6850c](https://github.com/conradomateu/pianpian/commit/0f6850c9de2191917d8dec1b032f0f75f52c9ac8))
* keep a whole whisper.cpp transcript when the GPU build then fails ([f80c141](https://github.com/conradomateu/pianpian/commit/f80c1411c82aa0ff5ecd37e0b7da144aaa210d66))
* keep job log lines whole across output chunks ([ab52bd5](https://github.com/conradomateu/pianpian/commit/ab52bd5e836bf71e72eff8e502b83bd77c0887ef))
* keep mobile word sheets reachable and desktop controls fitted ([e9cde3f](https://github.com/conradomateu/pianpian/commit/e9cde3f32cc921653692e3efee48fc751493e217))
* keep the setup and the jobs from running at the same time ([9bc0c2c](https://github.com/conradomateu/pianpian/commit/9bc0c2c172c210923aaa1ac76db90445bcdb9d19))
* keep the words of one OCR line in left-to-right order on Windows ([78bb0a5](https://github.com/conradomateu/pianpian/commit/78bb0a51be8e5d0285cd00b70f68ebbfec6ba17d))
* keep Windows checks encoding-safe ([5eec2dc](https://github.com/conradomateu/pianpian/commit/5eec2dc0bc78344e36b9d33b162e53a6aa391c7c))
* let the setup repair an engine that is there but cannot start ([c55a725](https://github.com/conradomateu/pianpian/commit/c55a725c76412307f8ee18d39a49d6b6da1ca3f1))
* merge the Windows installer and offer each platform its own update file ([92caf14](https://github.com/conradomateu/pianpian/commit/92caf14156efb95c28797dc5e9f1dc7701cc860e))
* never follow a link out of the library ([28985c1](https://github.com/conradomateu/pianpian/commit/28985c176dfd5b1fb21b41413d619b377062406f))
* open the website demo on its first subtitle line ([5711d0f](https://github.com/conradomateu/pianpian/commit/5711d0f798c955ce62a3240bb27f38c765cd2015))
* overwrite existing English lines when re-translating on Windows ([92fc4f1](https://github.com/conradomateu/pianpian/commit/92fc4f1ff348d681811c823a627a8be5bef7c939))
* print llama-server's last log lines when it dies mid-translation ([f8cb619](https://github.com/conradomateu/pianpian/commit/f8cb6199a47b01df1d5746f4c10dc932e261e50b))
* rebuild the engine only when its venv is broken, not when a check fails ([aa30ea1](https://github.com/conradomateu/pianpian/commit/aa30ea191ab6cd97411555d56a5d58ba77166fce))
* redact library names, joined user names and bare timestamps in reports ([8b832c8](https://github.com/conradomateu/pianpian/commit/8b832c83ae449dfecaf95c3fd18121836ac6350c))
* redact the other ways Windows writes a path in reports ([c954291](https://github.com/conradomateu/pianpian/commit/c954291499590cc222cdf21da897fd2c6e2baf6b))
* refresh cached word tracks after segmentation upgrades ([50dd556](https://github.com/conradomateu/pianpian/commit/50dd556b3eb429d2de90b9b3843bee5617f44fea))
* refuse requests for another Host and hide the library from other sites ([c176986](https://github.com/conradomateu/pianpian/commit/c1769865f122e48a141bbc8b20b91abbf137ea82))
* refuse Windows device names and answer path errors with a status ([3f69151](https://github.com/conradomateu/pianpian/commit/3f6915138b24140cf8d83d597fb2a7645ec32c46))
* replace a Windows runtime build whole when its pin changes ([5fb4487](https://github.com/conradomateu/pianpian/commit/5fb44878756e51cee5c99e49d492a9462f93a66f))
* run Anki's audio and retime processes without a console window and in UTF-8 ([049210a](https://github.com/conradomateu/pianpian/commit/049210a29e48c0ac7c1ada8f7d38688c9f1ed23d))
* run the model's word links only where the backend can align ([47dafca](https://github.com/conradomateu/pianpian/commit/47dafca88f30f4a76cec6fc2548aff640f61cb9e))
* serialize concurrent settings writes ([1e9a953](https://github.com/conradomateu/pianpian/commit/1e9a95393a3bc930011d6f182deb289527974474))
* show setup errors before installation starts ([7eebcf3](https://github.com/conradomateu/pianpian/commit/7eebcf31efa8072d4e8e4ef5f1d0a3c06ace1b46))
* split unknown study compounds and keep import errors private ([0f93d12](https://github.com/conradomateu/pianpian/commit/0f93d127961f797d2ab53bdb014073b3df6b4ac8))
* start llama-server at -lv 4 so the offload count reaches the job log ([30548ce](https://github.com/conradomateu/pianpian/commit/30548ceb85132a12b0c2a0404a5d82822da2546c))
* strip Bilibili's locale segment from shared links ([e5e8f93](https://github.com/conradomateu/pianpian/commit/e5e8f93238e94ef7bcd1184e1d0122a67260c368))
* tailor landing downloads to each platform ([b43a0e0](https://github.com/conradomateu/pianpian/commit/b43a0e0d8b7bcf80f0a5256d2fbd194f6c0d4196))
* take the downloads along when the setup's data folder changes ([4165099](https://github.com/conradomateu/pianpian/commit/41650996ad5c1d29b4d639e1efc50e28af7f194b))
* unquote video ids in POST endpoints ([c7fe9d4](https://github.com/conradomateu/pianpian/commit/c7fe9d4616d509b13665854e43ca97d386c32b3b))
* website shows at once when Google Fonts or Umami are slow or blocked ([c10b3d0](https://github.com/conradomateu/pianpian/commit/c10b3d073852e1c459d76ab9decd10efc70ef315))
* write config.json readable by its owner only ([5a79245](https://github.com/conradomateu/pianpian/commit/5a792456ce3a8e50fee8f654bc196da8303ed729))

## [0.1.4](https://github.com/conradomateu/pianpian/compare/pianpian-v0.1.3...pianpian-v0.1.4) (2026-11-07)


### Bug Fixes

* keep the demo thumbnail in its final player layout ([#24](https://github.com/conradomateu/pianpian/issues/24)) ([8c66d62](https://github.com/conradomateu/pianpian/commit/8c66d62b47903765532aff5938546962a5bee714))
* use a higher-resolution poster in the video player ([#26](https://github.com/conradomateu/pianpian/issues/26)) ([9ddcf54](https://github.com/conradomateu/pianpian/commit/9ddcf54092a08e5b6839878959049a202a1aa67d))

## [0.1.3](https://github.com/conradomateu/pianpian/compare/pianpian-v0.1.2...pianpian-v0.1.3) (2026-11-07)


### Bug Fixes

* build Mac releases on a supported Apple Silicon runner ([#22](https://github.com/conradomateu/pianpian/issues/22)) ([67ffd49](https://github.com/conradomateu/pianpian/commit/67ffd49b637e34148698c9dc1cb150a34f377e0d))

## [0.1.2](https://github.com/conradomateu/pianpian/compare/pianpian-v0.1.1...pianpian-v0.1.2) (2026-11-07)


### Bug Fixes

* show video loaders and start progressive playback sooner ([#20](https://github.com/conradomateu/pianpian/issues/20)) ([6f76586](https://github.com/conradomateu/pianpian/commit/6f76586a470c9ac06756caac588c0c094c968f2b))

## [0.1.1](https://github.com/conradomateu/pianpian/compare/pianpian-v0.1.0...pianpian-v0.1.1) (2026-10-23)


### Features

* a DMG to drag Pianpian to Applications, next to the zip ([0bdddba](https://github.com/conradomateu/pianpian/commit/0bdddba160d92d35feb1471cd6345900edea861e))
* pasted links work: share text, short links, tracking removed, temporary failures retried ([57b2da1](https://github.com/conradomateu/pianpian/commit/57b2da141ef6198156441dbb4847bfcde5f3a0aa))


### Bug Fixes

* the new-version card works with release-please's tags ([c6ab920](https://github.com/conradomateu/pianpian/commit/c6ab9207d436d9e2217139968eefba9a520c67c3))
* the packaged app no longer breaks its own signature by writing bytecode into itself ([e63d26d](https://github.com/conradomateu/pianpian/commit/e63d26daaed6844f690548a6b8557f41f72a9434))
* the release workflow can attach the DMG and rebuild the website ([8fc2cd7](https://github.com/conradomateu/pianpian/commit/8fc2cd77ff3a3ee3ffb324fc73777d23cf35653a))

## [0.1.0](https://github.com/conradomateu/pianpian/compare/pianpian-v0.0.1...pianpian-v0.1.0) (2026-10-23)


### Features

* "Try it in the demo" on each feature row of the website ([d7c2118](https://github.com/conradomateu/pianpian/commit/d7c211868128ad545562cd5665bd4a0dc7a3bdba))
* a first-run setup that installs the engine and the models with progress ([6f7b7ac](https://github.com/conradomateu/pianpian/commit/6f7b7ace361a9c1ed3630f8ad721b62325319cbf))
* a fuller website: practice line by line, feature rows, testimonials, FAQ ([53f98d1](https://github.com/conradomateu/pianpian/commit/53f98d102e9a944a54538e13f5a74a949913cc54))
* a one-line key for the tone colours in the Subtitles menu ([f781ff1](https://github.com/conradomateu/pianpian/commit/f781ff1dc92c26ddf4bae03730042500c4a298f4))
* a website with the app as a live demo, and screenshots made from it ([9669638](https://github.com/conradomateu/pianpian/commit/96696380067bc5df9bef375aabdd6b88ee8a9d7d))
* add dropped videos to the library; readable light theme; M2 groundwork ([71a36c6](https://github.com/conradomateu/pianpian/commit/71a36c60d849d600899df4edd8a2b4275c8de3ff))
* build Pianpian.app and attach it to every release ([a93f487](https://github.com/conradomateu/pianpian/commit/a93f4879d2ec1eb15a4c65a4a95982d33cc9c484))
* cheat sheet colours each part of the sentence, pinyin above each word ([b82b34e](https://github.com/conradomateu/pianpian/commit/b82b34e7ef69eeeb4efaff4d4543176db9356ccc))
* drop the burned-in option from the add form ([32fccdc](https://github.com/conradomateu/pianpian/commit/32fccdc18208fcfd2afef7ea21bf98e2838f958e))
* follow the voice; tenses optional and underline-only ([fa9b98c](https://github.com/conradomateu/pianpian/commit/fa9b98c579e33f88663a015740c6f911d49693e7))
* glide the library and transcript instead of resizing them ([7ad1526](https://github.com/conradomateu/pianpian/commit/7ad152642cc7ccdf0f480dd0b8f312dccd4702ed))
* Grammar menu is a lean cheat sheet: word order, past, future, now ([44ee6ae](https://github.com/conradomateu/pianpian/commit/44ee6ae0cd767bff39517539c2df990321f128db))
* library and transcript as two matching side panels ([07c13c2](https://github.com/conradomateu/pianpian/commit/07c13c2c63d7468914dd47924eb13f6a5135a2f4))
* music, a closing invitation to download, and cleaner drawings in the demo ([151d775](https://github.com/conradomateu/pianpian/commit/151d7757d6273dfcce8faaa3b58ff42b7e736123))
* one engine environment and a Python pipeline ([83e5e7b](https://github.com/conradomateu/pianpian/commit/83e5e7b2fa9e3e202ecfa8150822f7756331abaa))
* one screen with a folding library and a row of menus ([805c90d](https://github.com/conradomateu/pianpian/commit/805c90d0a7143a6028ff215f446e2b9d35058289))
* Pianpian.app, the app in its own window ([f194a12](https://github.com/conradomateu/pianpian/commit/f194a1296d01cefc4b736dc0a45790948845d532))
* pinyin under every example in the Grammar cheat sheet ([ce426c8](https://github.com/conradomateu/pianpian/commit/ce426c8f76fd2d8d69604fae7ea843d900f7e482))
* report a problem: plain hints for known failures, redacted details, GitHub's bug form filled in ([6a52cc2](https://github.com/conradomateu/pianpian/commit/6a52cc26a4c5b8e153f32463f925edb839a553c8))
* the Apple logo on the Download for Mac buttons (website and demo video) ([563df0f](https://github.com/conradomateu/pianpian/commit/563df0ff3f35bae9d61dc40bc491dd19cb5e7d15))
* the demo plays the festival music (过年 style) ([bbaa7d2](https://github.com/conradomateu/pianpian/commit/bbaa7d221fd3be1c545fca3b2e788a723d3e4a36))
* the demo's Pianpian speaks with a young boy's voice (Kokoro yunxia) ([d51df35](https://github.com/conradomateu/pianpian/commit/d51df357fba0d45daa54df8e550f015d5222fe28))
* the website lets the live demo show the app; the demo opens on the video ([3d796b1](https://github.com/conradomateu/pianpian/commit/3d796b1a709beefadb218b1ba51effaa2d6df574))
* tone colours, tense colours and HSK levels (M2) ([7235854](https://github.com/conradomateu/pianpian/commit/7235854f8ed5bf68fd6b251bb7f7ea4719e63675))
* updates: a new-version card, a weekly fresh downloader, pinned models, engine updates ([f8ca294](https://github.com/conradomateu/pianpian/commit/f8ca2947c93897db83738ddd4a9afb11b024611f))


### Bug Fixes

* keep the library above the content while it slides in ([6fdbaca](https://github.com/conradomateu/pianpian/commit/6fdbacae8cd7f2637bde1ea828bbefe2c9bea268))
* make the spoken word easy to see (amber) ([5673aea](https://github.com/conradomateu/pianpian/commit/5673aea05dac69b124891a1aa72d9b2cbc6e0cc6))
* one fixed library toggle and a full-width video ([c36a79b](https://github.com/conradomateu/pianpian/commit/c36a79b1c9f589942507b0abde823dcb02f857af))
* paths that work for anyone, not only on the author's Mac ([e45949b](https://github.com/conradomateu/pianpian/commit/e45949b6036eb8ad5310c06c42ce0515927ce2c8))
* pin each model file at its own ModelScope revision ([104d113](https://github.com/conradomateu/pianpian/commit/104d113633b10957b4797a9ac06964f67746ab78))
* plain pinyin in the word card; document M2 ([0931187](https://github.com/conradomateu/pianpian/commit/0931187a6d9100e28a8927872a1d89eb1222c540))
* room for the cheat sheet's pinyin on one line ([bd9134e](https://github.com/conradomateu/pianpian/commit/bd9134ea2913dbb65c419ba863f3d2aebea94b0c))
* spoken word on a soft grey instead of solid amber ([933479a](https://github.com/conradomateu/pianpian/commit/933479a5bad8db909dd357162bfffe3718b0d608))
* Whisper finds ffmpeg on a Mac without Homebrew ([ae046e5](https://github.com/conradomateu/pianpian/commit/ae046e55747cd4e9d3b25f6464a816af74980797))
* whole URLs for link previews, from site/CNAME once the domain is set ([7892186](https://github.com/conradomateu/pianpian/commit/789218676cab9b735170b285341a3e5959b0b600))


### Documentation

* a README for people arriving on GitHub: badges, download, pictures, install, credits ([89b81b1](https://github.com/conradomateu/pianpian/commit/89b81b18b2de0de57c1c0555d22898bcb4fa51c5))
* AGENTS.md and CLAUDE.md, the instructions for AI coding agents working on Pianpian ([deb44a0](https://github.com/conradomateu/pianpian/commit/deb44a028b0dc08574d6a3158d063274f250db84))
