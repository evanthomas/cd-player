# An old fasioned CD player

A Raspberry Pi appliance that behaves like an old-fashioned CD player, but plays to a
[Sonos](https://www.sonos.com/) speaker instead of built-in speakers. Insert a CD, and the
software identifies it and fetches metadata/artwork from MusicBrainz and the Cover Art
Archive. Playback is controlled via a small REST API.

Audio is ripped live and streamed to Sonos as it's extracted from the disc — nothing is
ripped to disk up front. Track lengths are known exactly from the disc's table of contents
before ripping starts, so the HTTP stream can advertise a correct `Content-Length` (and
support Range requests, which Sonos needs for pause/resume) while the track is still being
read off the disc.

## Hardware

- Raspberry Pi 5 (an earlier Pi didn't supply enough power for the optical drive plus the
  screen)
- USB optical drive
- A screen
- A Sonos speaker on the same LAN

## System dependencies

Audio extraction shells out to `cdparanoia`, and disc identification uses `libdiscid`:

```bash
sudo apt install cdparanoia libdiscid0
```

The touchscreen UI (`cd-player-ui`, see below) needs `pygame` built against the *system*
SDL2 -- the prebuilt PyPI wheel bundles its own SDL2 without KMSDRM support, which is what
lets it render straight to the framebuffer with no X11/Wayland compositor running:

```bash
sudo apt install python3-dev libsdl2-dev libsdl2-ttf-dev libsdl2-image-dev libsdl2-mixer-dev
```

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pip install --no-binary pygame -e ".[ui]"   # only if using the touchscreen UI
```

## Configuration

Configuration is entirely via command-line arguments (see `cd_player/config.py`).
Run `cd-player --help` for the full list.

| Argument | Required | Default | Purpose |
|---|---|---|---|
| `--speaker-name` | yes | — | Room/player name of the target Sonos speaker, as shown in the Sonos app (e.g. `Study`). Discovered on the network at startup |
| `--advertise-host` | yes | — | This Pi's LAN IP, reachable by the Sonos speaker (used to build stream URLs) |
| `--device-path` | no | `/dev/disk/by-id/usb-cd0` | Path to the optical drive. Use a stable `/dev/disk/by-id/...` symlink, not `/dev/sr0`, since drive enumeration order isn't guaranteed |
| `--db-path` | no | `/var/lib/cd-player/cache.db` | SQLite metadata cache (avoids re-querying MusicBrainz for a disc you've already seen) |
| `--artwork-dir` | no | `/var/lib/cd-player/artwork` | Cached cover art |
| `--stream-dir` | no | `/dev/shm/cd-player` | Where in-progress rips are written. Keep this on tmpfs — it's written continuously while a track plays |
| `--bind-host` | no | `0.0.0.0` | Interface the REST/streaming server binds to |
| `--bind-port` | no | `8080` | Port for the REST/streaming server |
| `--sonos-poll-interval` | no | `1.5` | Seconds between polls of Sonos's own transport state, used to detect play/pause triggered from the Sonos app itself |

The default `--db-path`/`--artwork-dir` live under `/var/lib`, which typically needs root
to create. Either run as a systemd service with a `StateDirectory=`, or point both at a
directory your user owns, e.g.:

```bash
mkdir -p ~/.local/share/cd-player/artwork
.venv/bin/cd-player \
  --db-path ~/.local/share/cd-player/cache.db \
  --artwork-dir ~/.local/share/cd-player/artwork \
  ...
```

## Running

```bash
.venv/bin/cd-player \
  --speaker-name Study \
  --advertise-host 192.168.1.41 \
  --device-path /dev/disk/by-id/usb-...
```

Inserting a disc only triggers identification (TOC read + metadata lookup) — it never
starts playback on its own. Playback always starts from an explicit `play` command.

## Touchscreen UI

`cd-player-ui` is a separate process that renders a landscape touch UI on the Pi's screen
(720x1280 native/portrait on the Pi Touch Display 2, rendered landscape and rotated in
software) directly to the DRM/KMS framebuffer -- no X11 or Wayland, so nothing to wait on
at boot. It's a REST client like any other: it polls `GET /status` and calls the same
`POST` endpoints as curl, so it can be started, stopped, or crash independently of
`cd-player` itself.

```bash
.venv/bin/cd-player-ui --api-base-url http://localhost:8080
```

| Argument | Default | Purpose |
|---|---|---|
| `--api-base-url` | `http://localhost:8080` | Base URL of the `cd-player` REST API |
| `--rotate` | `270` | Degrees (counterclockwise) to rotate the rendered UI onto the physical panel. Depends on the physical mounting orientation, not just the panel's native portrait mode; verify against the real screen -- taps landing on the wrong button means this needs adjusting |
| `--poll-interval` | `1.0` | Seconds between `/status` polls |

Behavior: black screen with no disc loaded; once a disc is loaded, shows cover art,
title/artist/track with elapsed/total time (filled in asynchronously as `/status` picks up
MusicBrainz/Cover Art Archive data and Sonos's playback position), and
skip-back/play/pause/skip-forward/eject buttons -- each dimmed and inert whenever it
wouldn't do anything (e.g. play while already playing, skip-forward on the last track).
Icons are drawn procedurally (no image assets to load).

## REST API

All control endpoints are `POST` and return the current player status as JSON.

| Endpoint | Effect |
|---|---|
| `POST /play` | If stopped, connects to the speaker and plays from track 1. If paused, resumes. |
| `POST /pause` | Pauses playback; stays connected to the speaker. |
| `POST /stop` | Stops playback and disconnects (clears the speaker's loaded source). |
| `POST /skip-forward` | Moves to the next track. No-op at the last track. |
| `POST /skip-backward` | Moves to the previous track. No-op at the first track. |
| `POST /eject` | Stops playback (if any) and opens the tray. |
| `GET /status` | Current player state, track number/bounds, elapsed/total track time, and disc metadata. |

```bash
curl -X POST http://localhost:8080/play
curl http://localhost:8080/status
```

The player also polls the speaker's own transport state, so pausing or resuming from the
Sonos app itself stays in sync with `/status`.

## Testing

```bash
.venv/bin/pytest tests/
```

The suite covers disc TOC math, WAV header construction, the player state machine
(including track-boundary no-ops, gapless auto-advance, and staying in sync with
externally-triggered Sonos state changes), the Range-request streaming server, and the
touchscreen UI's pure logic (status-to-view-model mapping, button layout, and the
portrait/landscape rotation geometry). None of it needs real hardware, and none of it
needs `pygame` installed -- the UI's rendering/touch-event code (`cd_player/ui/app.py`,
`renderer.py`, `icons.py`) is pygame-dependent and, like `disc/ripper.py` and
`streaming/stream_server.py`, is verified against the real screen instead.

## Known limitations

- Track titles don't currently show up in the Sonos app itself (Sonos regenerates its own
  display title from the stream URL for ad-hoc HTTP sources rather than trusting the
  provided metadata). Full track/artist/album info is always available via `/status`.
- A single, fixed Sonos speaker is supported, configured by room name and resolved via
  network discovery at startup — there's no runtime speaker selection or multi-room
  grouping, and the speaker must already be powered on and reachable when `cd-player`
  starts.
- If the optical drive can't keep up with playback (e.g. a heavily scratched disc), Sonos
  may stall waiting on the stream; this isn't actively handled.
- Restarting `cd-player` while Sonos is still playing from a previous run can leave
  `/status` reporting `"state": "playing"` with no track number, since the new process has
  no memory of what the old one started. `POST /stop` recovers cleanly.

## License

MIT — see [LICENSE](LICENSE).
