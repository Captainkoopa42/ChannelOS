# Jellyfin Live TV Adapter

> [!IMPORTANT]
> **Direction notice:** This file documents the experimental **outbound** adapter
> (`ChannelOS -> Jellyfin Live TV`). It is retained as an interoperability proof, but
> it is not the primary product direction. The intended integration keeps the
> ChannelOS interface and uses Jellyfin invisibly as an optional inbound library,
> metadata, and playback backend. See
> [JELLYFIN_BACKEND_MASTER_PLAN.md](JELLYFIN_BACKEND_MASTER_PLAN.md).

**Status:** Experimental source-tree proof

**Boundary:** ChannelOS Core -> M3U / XMLTV / MPEG-TS -> Jellyfin Live TV

ChannelOS can expose its persistent numbered channels to Jellyfin without making
Jellyfin part of ChannelOS Core. ChannelOS remains the schedule authority;
Jellyfin supplies its existing Guide, clients, networking, and transcoding
infrastructure.

```text
Channel definitions + indexed media
                |
                v
       ChannelRuntime / Broadcast Clock
                |
                v
       Jellyfin Live TV adapter
          |       |       |
          M3U   XMLTV   MPEG-TS
                |
                v
             Jellyfin
```

The adapter does not use or mutate the Viewer Clock or On Demand playhead. Each
Jellyfin tuner request watches the live Broadcast Clock, seeks into the current
scheduled file at the mathematically correct offset, and rolls into later
scheduled programs. Untuned channels still consume no decoder resources.

## Requirements

- a source checkout with Python 3.11 or newer,
- the normal ChannelOS library and runtime databases,
- one or more working channel YAML definitions,
- FFmpeg available on `PATH`, or supplied with `--ffmpeg`.

FFmpeg is required only for the live MPEG-TS channel endpoints. M3U and XMLTV
generation use the Python standard library and ChannelOS Core.

## Start the adapter

From an editable source installation:

```powershell
channelos jellyfin channels\channel-7.yaml channels\channel-12.yaml `
  --db "$env:LOCALAPPDATA\ChannelOS\library.db" `
  --state-db "$env:LOCALAPPDATA\ChannelOS\runtime.db"
```

The default same-PC endpoints are:

```text
http://127.0.0.1:4242/channels.m3u
http://127.0.0.1:4242/guide.xml
http://127.0.0.1:4242/channel/007.ts
```

The console prints the exact tuner and guide URLs. Keep it running while
Jellyfin imports the lineup or plays a channel.

## Add it to Jellyfin

In the Jellyfin administration dashboard:

1. Open **Live TV** and add an **M3U Tuner**.
2. Enter `http://127.0.0.1:4242/channels.m3u` as the tuner URL.
3. Add an **XMLTV** guide provider.
4. Enter `http://127.0.0.1:4242/guide.xml` as the guide URL.
5. Refresh tuner and guide data, then map channels if Jellyfin does not match
   the shared `channelos.<number>` identities automatically.

If Jellyfin runs in Docker, `127.0.0.1` inside its container is not the Windows
host. Bind ChannelOS to the LAN or container-reachable interface and explicitly
advertise the URL Jellyfin can reach:

```powershell
channelos jellyfin channels\channel-7.yaml `
  --db "$env:LOCALAPPDATA\ChannelOS\library.db" `
  --state-db "$env:LOCALAPPDATA\ChannelOS\runtime.db" `
  --host 0.0.0.0 `
  --advertise-url "http://192.168.1.50:4242"
```

This experimental server has no authentication. The default is deliberately
loopback-only. Do not expose it to the public internet; use a trusted local
network for multi-machine testing.

## Useful options

```text
--port 4242             HTTP port
--ffmpeg PATH           explicit FFmpeg executable
--guide-past-hours 6    past schedule included in XMLTV
--guide-hours 72        future schedule included in XMLTV
--max-streams 2         concurrent FFmpeg tuner sessions
```

`/health.json` provides a small readiness response. A missing FFmpeg executable
does not prevent M3U/XMLTV inspection, but live channel requests return HTTP
503 until FFmpeg is available.

## Current proof boundary

This is the deliberately thin first integration:

- M3U lineup generation,
- XMLTV generated directly from `GuideService`,
- live MPEG-TS generated from `ChannelRuntime.broadcast_at()`,
- numeric channel identity shared across all three surfaces,
- bounded concurrent streams,
- no Jellyfin plugin and no dependency on Jellyfin internals.

The first real-machine gate is Guide import plus sustained playback across a
scheduled program boundary. Only after that gate should ChannelOS consider a
thin native Jellyfin plugin or Windows packaging for this service.
