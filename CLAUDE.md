# CLAUDE.md

## Project Context
When working with this codebase, prioritize readability over cleverness. Ask clarifying questions before making architectural changes.

## Introduction
The overall goal is build a music CD player that play old fashioned CD player that will load CDs and play them to Sonos speakers on the local network. The physical components of the project are:
- a Raspberry Pi
- an optical drive connected by USB

The user will insert a CD into the drive. The software will retrieve CD information and artowrk from appropriate internet resources.

The initial interface will be via the command line, e.g. using REST POST calls to the main program. The software will respond to the following commands:
- play: If the CD is stopped, connect to the speaker and play from the beginning. If paused then resume play.
- pause: Pause play, do not disconnect from the speaker.
- stop: Stop play, disconnect from the speaker
- skip track forward 
- skip track backwards
The player will also respond to pause/restart commands issued to the speaker via the Sonos app.

## Commands

System deps (not pip-installable): `sudo apt install cdparanoia libdiscid0`.

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # setup
.venv/bin/pytest tests/                                       # run all tests
.venv/bin/pytest tests/test_state.py -v                       # single file
.venv/bin/cd-player                                            # run the app (needs env vars, see README.md)
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


