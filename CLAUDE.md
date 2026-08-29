# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Context
Prioritize readability over cleverness. Ask clarifying questions before making architectural changes.

A Raspberry Pi 5 + USB optical drive + screen appliance that behaves like an old-fashioned
CD player, but plays to a Sonos speaker instead of built-in speakers, controlled via a REST
API (`play`/`pause`/`stop`/skip forward/skip backward/eject) and a touchscreen UI. See
[README.md](README.md) for hardware, full CLI config, and the REST API table.

## Commands

`./setup.sh` (`--ui` to also build pygame from source for the touchscreen) installs system
packages, creates `.venv`, and installs the Python package -- automates the manual steps
below. Safe to re-run.

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # setup (what setup.sh automates)
.venv/bin/pytest tests/                                       # run all tests
.venv/bin/pytest tests/test_state.py -v                       # single file
.venv/bin/cd-player                                            # run the app (needs CLI args, see README.md / --help)
.venv/bin/cd-player-ui                                         # touchscreen UI, separate process (needs pygame, see README.md)
```

`./install-service.sh` installs `cd-player`/`cd-player-ui` as systemd services that start at
boot -- see the "Boot-time deployment" architecture note below before touching anything
under `deploy/`.

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
compositor). It's a REST client, nothing more: `ui/client.py`'s `PlayerClient` wraps the
actual HTTP calls, `ui/poller.py` polls `GET /status` through it on a background thread
(mirrors `sonos/poller.py`'s poll-not-push design), and `ui/app.py` dispatches button taps
(and, via its `VolumeSender`, throttled volume drags) to the same `POST` endpoints curl or
the Sonos app would hit. This
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

`SonosController` manages a *group* of speakers playing in sync, not just one fixed device:
`self._selected` is an ordered list of `soco.SoCo` objects where `self._selected[0]` is
always the group coordinator (every transport/volume/seek call targets it; UPnP requires
this — members just follow). The coordinator is deliberately "sticky" — `set_selected_speakers()`
only picks a new one when the current coordinator is actually deselected — so adding or
removing other speakers never disrupts ongoing playback with a needless handoff. Selection
is runtime-mutable (via the touchscreen's settings screen / `POST /speakers`) but never
persisted: `--speaker-name`'s speaker is always the sole starting selection on boot.
`PlayerStateMachine.set_selected_speakers()` handles the harder case — the coordinator
changing identity while a track is PLAYING/PAUSED — by reissuing `play_uri` to the new
coordinator and `seek()`ing back to the last known position (best-effort; a seek failure is
logged, not raised). `status()` never calls `SonosController.get_volume()` directly (it's a
live, uncached UPnP round trip per SoCo's `ZoneGroup.volume`) — volume is polled by
`SonosPoller` on its existing cadence and cached on the state machine, exactly like
`_elapsed_seconds`, so the single most-called endpoint in the app stays 100% in-memory.

### Boot-time deployment (`deploy/`, `install-service.sh`)

The appliance runs as two systemd services, `cd-player.service` and `cd-player-ui.service`
(`deploy/*.service`), installed by `install-service.sh` and started at boot via
`multi-user.target` — both run as plain `User=pi`; DRM (`/dev/dri/card*`) and touch input
(`/dev/input/event*`) are gated by static udev group rules on this hardware, not
`systemd-logind` per-session ACLs, so no root or session/PAM handling is needed. Runtime
config (`--speaker-name`/`--advertise-host`/`--device-path`) lives in `/etc/default/cd-player`
(templated from `deploy/cd-player.env.example`, created once by `install-service.sh` and
never overwritten on re-install) rather than the unit files, via systemd's own
`EnvironmentFile=` + `${VAR}` substitution in `ExecStart=` — note this substitutes each
`${VAR}` as one argument regardless of embedded spaces (e.g. a speaker named "Living Room"),
since it's systemd's own exec-line parsing, not a shell.

**Root is overlay-protected on this Pi (enabled 2026-08-27)** — `/` is a tmpfs-over-ext4
overlay (Raspberry Pi OS's `overlayroot`), so any write under `/` (including `/etc`,
`/home/pi/cd-player`'s working tree, and anywhere under `/var`) is discarded on the next
reboot, reverting to whatever was there when overlay was last (re-)enabled. `/boot/firmware`
is the only writable exception. This is why `cd-player.service` points `--db-path`/
`--artwork-dir` at `/mnt/cd-player-data` (a dedicated USB drive, ext4, mounted via a
permanent `/etc/fstab` entry by UUID, `nofail` so a missing drive doesn't hang boot) rather
than `/var/lib/cd-player` — the metadata cache/artwork need to actually persist, and nothing
under `/` does anymore. `RequiresMountsFor=/mnt/cd-player-data` on the unit makes the service
fail closed (won't start) rather than silently writing cache data to the overlay's ephemeral
tmpfs if that drive isn't mounted. Persistent edits to anything under `/` (a new fstab line,
a changed unit file, etc.) need `sudo overlayroot-chroot <command>` — it remounts the real
underlying filesystem (`/media/root-ro`) read-write and chroots into it for that one command,
which is much simpler than disabling overlay + rebooting to edit + re-enabling + rebooting
again. A local `git commit` made directly on this Pi that isn't pushed to `origin` before the
next reboot is lost the same way — `cd-player-boot.sh`'s fetch-on-boot is what actually
carries code changes across a power cycle now, not the on-disk working tree.

`cd-player.service`'s `ExecStartPre=-deploy/cd-player-boot.sh` (the leading `-` makes a
nonzero exit non-fatal) is what makes this self-updating: it waits up to
`CD_PLAYER_UPDATE_TIMEOUT_SECONDS` (default 120s) for `origin` to become reachable —
`network-online.target` alone only means the network stack is up, not that any specific
remote is actually reachable yet, since WiFi association/DHCP can still be settling — then
fast-forwards to the latest commit. It never touches uncommitted local changes or a diverged
branch (skips and logs instead), and a fully offline boot still starts `cd-player` with
whatever code is already on disk rather than blocking forever. `cd-player-ui.service` has no
`Requires=`/`BindsTo=` on `cd-player.service`, only `After=` — the UI's own poller already
tolerates the server being briefly unavailable (see above), so making the units fail
together would undo that.

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
  **This debounce directly sets the audible gap between tracks** — two confirmations means
  the gap is roughly 2x `--sonos-poll-interval`, not pre-ripping (already fast: the next
  track is normally fully ripped well before it's needed) or Sonos's own reconnect (also
  fast once triggered). Measured live 2026-08-28: at the previous 1.5s default,
  `elapsed_seconds` sat frozen for ~2.4s before the next track appeared playing; lowering
  the default to 0.5s (now `CD_PLAYER_SONOS_POLL_INTERVAL` in `/etc/default/cd-player`) cut
  the same measured gap to ~0.35s on a repeat test. Don't lower it further without
  re-verifying the blip-filtering still works — the debounce's safety margin shrinks along
  with the interval.
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
  `on_sonos_state()` needs to either ignore a learned PLAYING with no known track, or map it back to a real track from Sonos's reported position/URI.
- **Multi-speaker grouping was verified against 3 real Sonos speakers (2026-08-27)**:
  hard-stop-before-unjoin does actually silence a dropped speaker (confirmed via direct
  `soco` query — `STOPPED`, empty `CurrentURI`, standalone coordinator of itself); the
  reissue → pause → seek sequence on a mid-track coordinator handoff preserves playback
  position and resumes into the correct PLAYING/PAUSED state on the new coordinator, with no
  spurious auto-advance. One real bug was found and fixed this way: `SonosPoller` read
  `SonosController`'s selection state directly, unsynchronized with REST-triggered
  `set_selected_speakers()` calls — fine for the old single fixed `self._device` (set once,
  never reassigned), but a race once `self._selected` became runtime-mutable (a `/speakers`
  POST landing between the poller's `has_selection()` check and its next call could raise
  "no speakers selected" mid-poll, reproduced directly by rapid-toggling speakers while
  playing). Fixed with a dedicated `threading.RLock()` inside `SonosController` itself,
  independent of `PlayerStateMachine._lock`.
- **The volume slider's on-screen fill lags behind a live drag by up to ~2.5s, and jumps
  when speakers are toggled** (confirmed on real hardware, 2026-08-27; not yet fixed). Two
  distinct causes: (1) `speaker.group.volume` is *derived* live across whichever speakers
  are currently grouped, not something the app owns, so adding a speaker with a different
  individual volume visibly shifts the reported group volume the moment membership changes
  — this is real Sonos behavior, not a UI bug. (2) the rendered slider position reads
  `ViewState.volume`, which only updates once `SonosPoller` re-polls the real coordinator
  (every `--sonos-poll-interval`, default 1.5s) *and* `cd-player-ui`'s own `/status` poll
  picks that up (every `--poll-interval`, default 1.0s) — `VolumeSender`'s throttled *send*
  path works correctly (confirmed: dragging does change the real speaker's volume promptly),
  but nothing feeds the locally-dragged value back into what's rendered while dragging is in
  progress. Fixing (2) means rendering from a local optimistic value during an active drag,
  falling back to the polled `ViewState.volume` on release — deliberately left as follow-up
  UI polish rather than fixed alongside the initial feature.


