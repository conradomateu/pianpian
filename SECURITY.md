# Security

Please don't open a public issue for a security problem. Use GitHub's private report instead: on the
repository, **Security → Report a vulnerability**
([direct link](https://github.com/conradomateu/pianpian/security/advisories/new)). Say what you found, how to
reproduce it and which version.

This is one person's spare-time project, so a reply can take a few days. Only the latest release gets fixes.

Of most interest: bypasses of the local server's loopback-only binding, local `Host` check,
`X-Kit: 1` POST/PUT guard or resolved library-path checks; cross-origin leaks beyond the public
`ok`/`version` status; reports that leak private details (`report.py`); and unverified engine, model
or runtime downloads. Setup and queued pipeline/downloader jobs must not overlap.

The optional AnkiConnect API key is stored in clear text in `config.json`. Settings writes are serialized
across threads in the app process and atomically replace that file with POSIX mode `0600` (owner
read/write only); this does not establish Windows ACL protection. Windows ACLs have not been verified.
`/api/anki/status` does not return the key. [Implementation details](ARCHITECTURE.md#server-api).

Problems in video sites, yt-dlp or the models belong upstream.
