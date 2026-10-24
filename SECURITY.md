# Security

Please don't open a public issue for a security problem. Use GitHub's private report instead: on the
repository, **Security → Report a vulnerability**
([direct link](https://github.com/conradomateu/pianpian/security/advisories/new)). Say what you found, how to
reproduce it and which version.

This is one person's spare-time project, so a reply can take a few days. Only the latest release gets fixes.

Of most interest: a way around the local server's checks (127.0.0.1 only, the `X-Kit: 1` header, path
checks), reports that leak what they promise to leave out (`report.py`), and unverified downloads of the
engine, models or updates. Problems in video sites, yt-dlp or the models belong upstream.
