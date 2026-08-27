# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Context
Prioritize readability over cleverness. Ask clarifying questions before making architectural changes.

A Raspberry Pi 5 + USB optical drive + screen appliance that behaves like an old-fashioned
CD player, but plays to a Sonos speaker instead of built-in speakers, controlled via a REST
API (`play`/`pause`/`stop`/skip forward/skip backward/eject) and a touchscreen UI. See
[README.md](README.md) for hardware, full CLI config, and the REST API table.

## Commands

System deps (not pip-installable): `sudo apt install cdparanoia libdiscid0`.

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # setup
.venv/bin/pytest tests/                                       # run all tests
.venv/bin/pytest tests/test_state.py -v                       # single file
.venv/bin/cd-player                                            # run the app (needs CLI args, see README.md / --help)
.venv/bin/cd-player-ui                                         # touchscreen UI, separate process (needs pygame, see README.md)
```

The test suite needs no real hardware (CD drive, Sonos speaker) — it runs entirely against
fakes/doubles. Real-hardware behavior in this project has repeatedly diverged from what
unit tests predict (see Gotchas below); when changing `disc/ripper.py`,
`streaming/stream_server.py`, or `sonos/`, treat passing unit tests as necessary, not
sufficient — verify against the real Pi/drive/speaker before considering a change done.

## Architecture

`cd_player/state.py` is the hub: one `PlayerStateMachine`, one lock, every transition
(REST-triggered or learned from polling Sonos) funnels through it, so a state change
learned *from* Sonos never re-issues the command that would just echo it back.

The core design problem this project solves: Sonos speakers pull audio over HTTP rather
than accepting pushed audio, and CDs are ripped *live* rather than fully ripped to disk
first. `disc/ripper.py`'s `RipSession` owns a `cdparanoia` subprocess writing into a
growing tmpfs file; `streaming/stream_server.py` serves Range requests against it,
blocking on a condition variable for not-yet-ripped bytes. Track length in PCM bytes is
known exactly from the disc TOC (`disc/toc.py`) before a single byte is ripped, so the
HTTP response can advertise a correct `Content-Length` from the start — this is what lets
Sonos treat it as a normal seekable track instead of an open-ended stream.

`state.py` also pre-rips one track ahead once the current track's rip finishes (drive
freed up), so end-of-track auto-advance is gapless — but never two tracks at once, since
one physical drive can't be read by two `cdparanoia` processes concurrently.

`disc/monitor.py`'s `DiscMonitor` watches the drive via `pyudev` and drives disc
identification on insert/eject; it never starts playback itself (that's always an explicit
REST `play`). On insert it reads the TOC (`disc/toc.py`), checks `metadata/cache.py`'s
SQLite cache by disc ID, and on a miss queries MusicBrainz + the Cover Art Archive
(`metadata/musicbrainz.py`, `metadata/coverart.py`) before handing the TOC and metadata to
`PlayerStateMachine.set_disc()`. `main.py`'s `create_app()` is where all of this — state
machine, registry, controller, monitor, poller, Flask blueprints — gets wired together.

`cd_player/ui/` is `cd-player-ui`, a separate process/console script rendering a landscape
touch UI straight to the DRM/KMS framebuffer (SDL2's `kmsdrm` video driver — no X11/Wayland
compositor). It's a REST client, nothing more: `ui/poller.py` polls `GET /status` on a
background thread (mirrors `sonos/poller.py`'s poll-not-push design) and `ui/app.py`
dispatches button taps to the same `POST` endpoints curl or the Sonos app would hit. This
keeps a rendering crash from ever touching the audio-critical ripping/streaming code in
`cd-player` itself, at the cost of REST round-trip latency per tap. `ui/view_model.py`,
`ui/layout.py`, and `ui/rotation.py` are pure and unit-tested (status→view mapping, button
hit-testing, and the portrait-panel↔landscape-canvas coordinate math); `ui/app.py`,
`ui/renderer.py`, and `ui/icons.py` depend on `pygame` and are verified against the real
screen instead, same as `disc/ripper.py`/`streaming/stream_server.py`.

Track *duration* is known locally from the TOC before ripping starts (same number
`_start_track` already hands Sonos as `<res duration=...>`); track *position* is not --
audio is streamed live and actually played by Sonos, so `SonosPoller` also polls
`SonosController.get_position_seconds()` (parses SoCo's `GetPositionInfo` `H:MM:SS`) each
tick and feeds it to `PlayerStateMachine.on_sonos_position()`. Both are exposed on
`/status` as `elapsed_seconds`/`track_duration_seconds`, reset together with
`current_track_number` on every stop/eject/track change (see `_reset_playback_position()`).

`config.py` builds `Config` from CLI args (`argparse`), not environment variables —
`load_config()`/`build_arg_parser()` are the source of truth for flags and defaults, not
the README table (keep both in sync when adding a flag). The Sonos speaker is identified
by room name (`--speaker-name`, e.g. `Study`), not IP: `SonosController.__init__` resolves
it via `soco.discovery.by_name()` at startup, which blocks on a network scan and raises if
the speaker isn't found — the speaker must be powered on and reachable before `cd-player`
starts.

### Gotchas (found via real-hardware testing, not from reading Sonos/UPnP docs)

- **Sonos infers content type from the URL's file extension.** An extensionless stream URL
  gets rejected outright (`UPnP Error 714`). Stream routes must end in `.wav`.
- **`soco.play_uri(title=...)` without explicit `meta=` tags content as
  `audioItem.audioBroadcast`** (radio), which never reports playback position and
  eventually stalls. `sonos/controller.py` hand-builds `audioItem.musicTrack` DIDL-Lite
  with an explicit duration instead — never use the `title=` shortcut for real playback.
- **UPnP `Stop` does not clear the loaded `CurrentURI`.** The Sonos app keeps showing the
  last-loaded track after stop unless you explicitly `SetAVTransportURI` with an empty
  URI — `SonosController.stop()` does this.
- **Sonos will not display a custom track title for ad-hoc HTTP audio**, no matter what
  `dc:title` you send — it regenerates one from the stream URL. This looks like it wants
  ICY/Shoutcast-style in-stream metadata instead (Sonos reflects an `<r:streamContent>`
  field). Not implemented; see README's Known Limitations. Don't re-attempt DIDL-only
  fixes for this without reading that note first.
- **A generator that waits for the *end* of the requested Range, not the next chunk,
  silently defeats live streaming.** A whole-file GET has an end far in the future, so
  waiting for it up front blocks the entire response on the full rip finishing. Any change
  to `stream_server._read_range`'s wait/chunk loop needs a timing-based test (see
  `test_full_request_streams_incrementally_not_only_at_completion`), not just a
  final-bytes-correctness test — Flask's test client buffers whole responses and can't
  catch this class of bug.
- **`RipSession.start()` must create the PCM file synchronously** before returning (not
  inside the background pump thread) — otherwise a fast client request can race the pump
  thread and see "file does not exist".
- Match `stop()`/`SIGTERM` against `RipSession._stopping`, not process return code alone —
  an intentional kill and a real crash both produce a non-zero/negative return code.
- **The PyPI `pygame` wheel bundles its own SDL2 without KMSDRM support** — `SDL_VIDEODRIVER=kmsdrm`
  silently has no display driver to use. Must `pip install --no-binary pygame` so it builds
  against the system `libsdl2-dev` (which Raspberry Pi OS does compile with KMSDRM), after
  `apt install python3-dev libsdl2-dev libsdl2-ttf-dev libsdl2-image-dev libsdl2-mixer-dev`.
- **The Pi Touch Display 2 reports a native portrait DRM mode** (`720x1280`), so the landscape
  UI is rendered onto a separate canvas and rotated onto the real display surface via
  `pygame.transform.rotate`, with `ui/rotation.py` doing the matching inverse transform on
  touch coordinates. The correct `--rotate` value depends on the physical mounting orientation,
  not just the reported DRM mode, so it's changed before: originally `90`, confirmed correct
  against the real screen and touch digitizer; after the display was remounted in a case
  (2026-08-27) the panel sits 180° from before, so `ui/app.py`'s default was updated to `270`
  and re-confirmed (rotation upright, taps landing on the right buttons). Don't assume the
  current default generalizes to other panels/mountings without re-verifying on real hardware.
- **A fresh `play_uri()` call from a STOPPED baseline can make Sonos report a single spurious
  `STOPPED` tick before settling into `PLAYING`** — a transient blip in the
  `SetAVTransportURI`+`Play` handshake, confirmed via `GetPositionInfo`/transport-state
  logging 2026-08-20: the *next* poll after that blip reliably shows `PLAYING` and the track
  plays normally afterward. `on_sonos_state()`'s `STOPPED` branch used to treat any single
  `STOPPED` report as end-of-track and immediately auto-advance — which, on the very first
  track after `play()`, meant it reliably skipped straight to track 2 within one poll
  interval. This is almost certainly what earlier looked like "button mashing" or a
  "runaway auto-advance loop" in prior sessions. Fixed by requiring two consecutive
  `STOPPED` polls (`_pending_stop_confirmations`) before treating it as real — a genuine
  end-of-track keeps reporting `STOPPED` on the next poll too, a blip doesn't. Only
  auto-advance-on-STOPPED needed this guard; tracks started via an already-active Sonos
  session (skip, gapless auto-advance) never exhibited the blip.
- **Rapid successive commands (e.g. mashing skip-forward on the touchscreen) can make the
  REST API itself time out**, not just queue up track changes: each state-changing call holds
  `PlayerStateMachine._lock` across a real network call to Sonos (`play_uri`) and a
  `cdparanoia` subprocess spawn/kill, so several quick taps back-to-back can leave a later
  `/status` or button-tap request waiting behind them long enough to read-timeout client-side
  (observed with `cd-player-ui`'s 3s timeout, 2026-08-20). Not a bug in the usual sense —
  each command does complete — but worth keeping in mind if adding debouncing/rate-limiting
  to `cd-player-ui`, or if a client's timeout needs to be more forgiving than 3s.
- **Killing `cd-player` doesn't stop Sonos** — it keeps playing whatever URL it was last
  given. If a new process starts (or restarts) while Sonos is still mid-playback from a
  *previous* process, `SonosPoller` will see `PLAYING` on its very first tick and
  `PlayerStateMachine.on_sonos_state()`'s `PLAYING` branch sets `self._state = PLAYING`
  without ever setting `_current_track_number` (that field is only assigned by
  `_start_track()`, on the "we initiated this" path) — producing a live but internally
  inconsistent `{"state": "playing", "current_track_number": null}`. Reproduced 2026-08-20:
  looked like "play starts on the wrong track" from `cd-player-ui` when it was really a
  leftover stream from an earlier dev-restart. `POST /stop` recovers cleanly. Not yet fixed;
  `on_sonos_state()` needs to either ignore a learned PLAYING with no known track, or map it
  back to a real track from Sonos's reported position/URI.


