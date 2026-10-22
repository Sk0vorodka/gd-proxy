# GD Proxy Helper (artem.gd-proxy)

Geode mod for Geometry Dash 2.2091 that routes ALL of GD's own downloads
(levels, level lists, music, song info, leaderboards) through a local proxy
so they **always succeed on the first attempt**.

## Why

GD downloads through libcurl, which honours the standard `http_proxy` /
`https_proxy` environment variables. This mod just points the game at a
tiny localhost proxy that:

1. **Retries** failed upstream requests a few times with backoff — this is
   what turns "first attempt fails, second succeeds" into "first attempt
   succeeds".
2. **Caches** every successful response on disk, so repeat downloads
   (songs, levels) are instant and work even if the source is down.

No game internals are hooked; no files in the game folder are touched; the
game's own client (levels/lists/music) is unchanged. HTTPS (CONNECT) is
tunnelled raw — no MITM.

## Setup

1. Install Python 3 if you don't have it.
2. Start the proxy: double-click `start-proxy.bat` (or
   `python tools/gdproxy.py --port 8080`). It listens on 127.0.0.1 only.
   Keep the window open while playing.
3. Launch GD → Geode Mods → **GD Proxy Helper** → set **Proxy URL** to
   `http://127.0.0.1:8080`. (Leave empty to disable the mod.)
4. Restart GD (or reload the mod). Every download now goes through the
   proxy.

The cache is stored in `tools/gdproxy-cache/`. Delete that folder any time
to clear it. Use a different port with `--port NNNN` and match it in the
mod setting.

## Notes

- The proxy must be running whenever the setting is non-empty; otherwise
  the game's downloads will fail (they have nowhere to go).
- Only connect the proxy to a source you trust. This is meant to run
  locally on your own machine, not as a public service.
- Music that is already downloaded by GD (files in `%LOCALAPPDATA%\GeometryDash\*.mp3`)
  doesn't need the proxy at all; the proxy only helps the download step.
