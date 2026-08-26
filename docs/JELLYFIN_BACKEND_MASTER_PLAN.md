# ChannelOS + Jellyfin Backend Master Plan

> **ChannelOS is the television. Jellyfin is an optional media warehouse behind it.**

**Status:** Living architecture and implementation plan  
**Document version:** 0.2 — August 26, 2026  
**Target branch:** `ChannelOS-for-Jellyfin`  
**Jellyfin baseline reviewed:** Server 10.11.11  
**Relationship:** Optional inbound media-source integration; not a Jellyfin UI replacement for ChannelOS

---

## 1. Purpose

This document defines the intended relationship between ChannelOS and Jellyfin.

The product direction is not:

```text
ChannelOS schedules -> Jellyfin Live TV -> Jellyfin interface
```

That direction was useful as an outbound interoperability experiment, but it puts the
wrong product in front of the viewer.

The intended direction is:

```text
Jellyfin library + metadata + network delivery + transcoding
                            |
                            v
                    ChannelOS adapters
                            |
                            v
ChannelOS Library + Channel Runtime + Guide + Broadcast Clock
                            |
                            v
                 ChannelOS couch interface
```

Jellyfin should feel like an invisible optional capability inside ChannelOS. A user who
connects a Jellyfin server should gain access to remote libraries, metadata, artwork,
and server-assisted playback without being sent into Jellyfin's web interface for
routine viewing.

The user still turns on ChannelOS, browses ChannelOS, builds ChannelOS channels, tunes
through ChannelOS, and sees ChannelOS's Guide.

---

## 2. Product promise

The integration should make this statement true:

> **ChannelOS can use media stored anywhere Jellyfin can serve while remaining
> ChannelOS in identity, behavior, scheduling, and presentation.**

The local-only product must remain complete. Jellyfin is an enhancement and a source,
not an entitlement system or mandatory dependency.

### 2.1 Zero-terminal user experience

The setup performed during the first proof used multiple PowerShell windows, a visible
Jellyfin server console, manually copied localhost URLs, M3U/XMLTV configuration, and
separate browser administration. That is an engineering test harness, not an
acceptable product workflow.

For an ordinary user, the complete relationship should be:

```text
One-time Jellyfin administration
    install or connect to Jellyfin
    sign in
    add/organize media libraries
                |
                v
ChannelOS Settings -> Media Sources -> Add Jellyfin
    discover or enter server once
    sign in / Quick Connect
    choose libraries
                |
                v
Everything else happens inside ChannelOS
```

The user may return to Jellyfin's own administration interface when they intentionally
need to add storage, change server metadata providers, manage Jellyfin accounts, or
perform other server-administrator work. Routine television use must not require it.

After the server is connected, ChannelOS owns the integration experience:

- server discovery and connection testing;
- login and token renewal prompts;
- library selection and synchronization;
- cached metadata and artwork;
- local/server source labeling;
- Channel Studio and Add to Channel workflows;
- Guide generation and source dividers;
- stream negotiation, playback, seeking, and program transitions;
- server health, reconnect, retry, and offline presentation;
- removal of a Jellyfin source from ChannelOS;
- all ordinary diagnostics that a nontechnical user needs.

### 2.2 What a normal user must never need to do

A packaged ChannelOS release must not require an ordinary user to:

- open PowerShell, Command Prompt, or a terminal;
- run Python, pip, FFmpeg, or ChannelOS CLI commands;
- keep multiple console windows open;
- copy `127.0.0.1`, port numbers, API routes, M3U URLs, or XMLTV URLs;
- create or manage Jellyfin API keys manually;
- configure ChannelOS as a Jellyfin Live TV tuner;
- read server logs to determine whether a source is connected;
- manually start an integration adapter every time ChannelOS launches;
- understand which background helper performs metadata or playback work.

Any ChannelOS-owned sync worker, authenticated playback relay, cache manager, or
health monitor must run inside the packaged application or as a properly managed
background component with no visible console window. ChannelOS starts it, monitors it,
recovers it, and stops it.

### 2.3 Local and remote server lifecycle

ChannelOS should distinguish between:

- **same-PC Jellyfin:** normally installed as a tray application or Windows service;
- **remote Jellyfin:** running on another PC, NAS, appliance, or hosted server.

For a same-PC server, ChannelOS should detect that Jellyfin is installed and report
`Running`, `Stopped`, `Starting`, or `Unavailable` in plain language. A future
explicit setting may allow ChannelOS to request that the local server start with
ChannelOS, but ChannelOS must not silently install, reconfigure, elevate, or take
ownership of Jellyfin.

For a remote server, ChannelOS cannot start the machine or service. It should retain
the cached catalog, show the named server as offline, retry sensibly, and allow the
user to continue watching all local media.

### 2.4 Finished-product acceptance test

The integration is not product-ready until a nontechnical Windows user can complete
this flow without a terminal:

1. install or already possess a Jellyfin server;
2. add media through Jellyfin's own setup/administration experience;
3. open ChannelOS;
4. choose **Add Jellyfin Server**;
5. discover or enter the server and sign in;
6. choose visible libraries;
7. browse that media in ChannelOS;
8. add server media to a ChannelOS channel;
9. see the local/server divider in the ChannelOS Guide;
10. tune and watch it without opening Jellyfin again.

That is the minimum user-experience gate, not optional polish.

### A connected user should gain

- Jellyfin libraries inside the ChannelOS Library experience;
- Jellyfin titles, descriptions, years, genres, tags, people, ratings, and hierarchy;
- posters, backdrops, thumbnails, and other useful images;
- remote playback from another PC or home server;
- Direct Play when possible and server transcoding when necessary;
- server-reported technical media and stream information;
- optional access to Jellyfin users, permissions, favorites, and watch state;
- server health and availability information;
- an explicit visual distinction between local and server-backed television.

### A connected user must not lose

- ChannelOS's couch-first Qt/QML interface;
- numbered persistent channels;
- the Broadcast Clock and Viewer Clock;
- ChannelOS's Guide and schedule truth;
- Channel Studio / Broadcaster intent;
- readable, portable channel definitions;
- local playback speed and offline behavior;
- ownership of local files and local state;
- the ability to remove Jellyfin without breaking local ChannelOS.

---

## 3. Constitutional boundaries

These are hard architectural constraints.

### 3.1 ChannelOS remains authoritative for television

ChannelOS owns:

- channel numbers and channel identity;
- programming rules;
- schedule generation;
- Broadcast Clock state;
- Viewer Clock state;
- Now / Next and Guide projections;
- tune, pause, rewind, return-to-live, and channel-switch semantics;
- Channel Studio and Broadcaster configuration;
- the ChannelOS interface.

Jellyfin item order, playlists, Live TV schedules, or playback sessions must not become
ChannelOS schedule truth.

### 3.2 Local operation remains first-class

When Jellyfin is disconnected, stopped, upgrading, or unreachable:

- local media and local channels continue to work normally;
- the ChannelOS application still launches;
- the Guide still opens;
- server-backed rows are visibly unavailable rather than silently removed;
- schedules do not mutate merely because a server is temporarily offline;
- no local feature asks a Jellyfin server for permission.

### 3.3 Jellyfin is a source, not the canonical library

ChannelOS may cache a projection of Jellyfin items, but Jellyfin item IDs must be stored
as provider/source references rather than treated as universal media identity.

The same conceptual title may have:

- a local ChannelOS file location;
- one or more Jellyfin locations;
- multiple Jellyfin versions or media sources;
- different availability at different times.

ChannelOS needs an identity and location model capable of representing those facts
without equating an asset with a filesystem path or one server's database ID.

### 3.4 Local playback is preferred when equivalent media is available

For a media item with a verified usable local location and a Jellyfin location,
ChannelOS should choose the local location by default.

Reasons:

- lower startup latency;
- no network dependency;
- no server transcoding load;
- smoother seeking and channel changes;
- preservation of local-first behavior.

The preference is a policy, not an unsafe guess. ChannelOS must not automatically
declare two files identical based only on similar titles. Automatic equivalence needs
strong evidence; ambiguous matches require review or remain separate.

### 3.5 Provider secrets remain private

Access tokens and API keys must never be:

- written into channel YAML;
- embedded in portable exports;
- displayed in ordinary logs;
- included in crash messages;
- persisted inside artwork or playback cache keys;
- sent to a server other than the configured Jellyfin origin.

Windows Credential Manager or another platform credential vault is the preferred
long-term token store. A source-tree proof may use an explicitly local development
store, but it must be clearly marked and excluded from portable exports.

---

## 4. Current ChannelOS architecture audit

The current codebase already has strong boundaries that should be preserved.

| Area | Current implementation | Integration consequence |
|---|---|---|
| Portable channels | `models.py` uses schema `0.1` and path-only `SourceDefinition` | A versioned source selector is required; remote IDs must not be disguised as paths |
| Media index | `library.py` stores SHA-256 `MediaAsset` plus one or more `MediaLocation` rows | Keep stable asset/location separation, then generalize locations beyond `Path` |
| Local discovery | `scanner.py` walks files, hashes content, and probes with ffprobe | Preserve as the local adapter; do not force remote items through filesystem scanning |
| Channel resolution | `resolve.py` resolves path selectors into `IndexedMedia` | Introduce provider-neutral selectors and a resolver registry |
| Scheduling | `runtime.py` schedules stable `IndexedMedia` with positive durations | Remote projections must provide stable IDs and authoritative positive duration |
| Guide | `guide.py` derives labels from `location.path.stem` | Guide programs need cached presentation metadata and source provenance |
| Couch projection | `couch_model.py` creates QML rows from authoritative Guide data | Add source sections/badges without moving schedule math into QML |
| Playback contract | `playback.py` accepts local `Path` values | Generalize `load()` around a `PlaybackTarget` that can describe paths or authenticated streams |
| Television playback | `television.py` reads `selected.location.path` directly | Ask a playback resolver for the best usable target before touching the backend |
| On Demand | `on_demand.py` is intentionally separate from channel clocks | Preserve that separation for Jellyfin On Demand playback and watch-state sync |
| Artwork | `artwork.py` finds sidecars or extracts local frames | Add provider artwork retrieval and local caching behind the same presentation boundary |
| Settings | `settings.py` stores small local user-owned preferences | Add server definitions separately; do not place tokens in the ordinary JSON settings file |

### 4.1 The main technical constraint

`IndexedMedia` currently assumes that every playable item has a local `Path`. That
assumption appears in the library, resolver, Guide labels, artwork extraction,
television session, and On Demand session.

Changing only `LibVLCBackend` would therefore be insufficient. The safe change is to
generalize media locations and playback resolution while leaving scheduling and the
television service boundary intact.

---

## 5. Jellyfin capability inventory

Jellyfin exposes more capability than ChannelOS should adopt at once. This matrix
distinguishes what Jellyfin offers from how ChannelOS should use it.

| Jellyfin capability | Value to ChannelOS | Intended posture |
|---|---|---|
| Virtual libraries containing multiple server paths | Remote media organization | Adopt as browseable source roots |
| Movies, series, seasons, episodes, music videos, home videos, music, books, photos | Rich typed hierarchy | Adopt video types first; defer non-video presentation |
| Search, filters, sorting, genres, tags, studios, people, years, ratings | Better Library and Channel Studio selection | Adopt incrementally through cached metadata |
| Collections and playlists | Useful source selectors and shelves | Import as references; do not make them ChannelOS channels automatically |
| TMDb, OMDb, local NFO, and plugin metadata providers | Identified titles and descriptions | Consume returned metadata; Jellyfin provider configuration stays in Jellyfin |
| Posters, backdrops, logos, thumbnails, chapter images | Polished ChannelOS presentation | Cache locally with provider ETags/image tags |
| Media sources, versions, containers, codecs, resolutions, audio/subtitle streams | Playback decisions and technical display | Adopt for playback negotiation and Info screens |
| Direct Play | Lowest server cost and best quality | Prefer for server-only media when client-compatible |
| Remux / Direct Stream | Compatibility without full video transcode | Allow when selected by Jellyfin playback negotiation |
| Video/audio transcoding and hardware acceleration | Playback across network/device limits | Adopt as server-assisted fallback |
| HDR tone mapping | Compatibility on displays that need SDR | Expose through the Jellyfin playback profile; do not reimplement initially |
| Subtitles and audio-track selection | Complete viewing experience | Phase after basic playback, represented in ChannelOS controls |
| Chapters | Navigation and richer Info | Adopt later; never alter Broadcast Clock math |
| Typed media segments such as intro/commercial/outro | Optional skip controls and programming insight | Defer; never silently rewrite a ChannelOS schedule |
| Per-user library access and parental controls | Household filtering | Respect Jellyfin visibility for Jellyfin items; keep ChannelOS local policy separate |
| Favorites, played state, resume position, play count | Cross-client continuity | Optional two-way sync with explicit conflict rules |
| Playback start/progress/stop reporting | Correct Jellyfin session and watch state | Required when watch-state integration is enabled |
| Quick Connect and username/password authentication | Couch-friendly server connection | Prefer Quick Connect when enabled; support manual login |
| API keys | Headless administration/integration | Avoid as the default household login; use least privilege where applicable |
| WebSocket notifications and sessions | Faster library/state updates | Add after polling sync is reliable |
| Server discovery and public system information | Easier setup and compatibility checks | Adopt with manual URL always available |
| Endpoint local/network classification | Playback policy and status display | Use as one signal; do not assume it measures actual quality |
| Remote access, reverse proxies, TLS, and VPN deployment | Access beyond the server machine | Support configured HTTPS URLs; ChannelOS does not automatically expose Jellyfin |
| Multiple official clients | Evidence of a stable client/server role | ChannelOS becomes another client, not a wrapper around Jellyfin Web |
| SyncPlay and remote session control | Future shared viewing and device control | Defer; not inherited merely by connecting the server |
| Downloads | Possible opt-in offline copies | Future explicit feature; never silently duplicate a remote library |
| Live TV and DVR | Additional remote broadcast/recording source | Defer and keep separate from ChannelOS schedule authority |
| Plugin catalog | Additional metadata/authentication/server features | Benefit only through stable API results; no required ChannelOS server plugin initially |
| DLNA/casting | Possible device-output path | Future adapter; not part of the first Jellyfin backend |
| Server tasks, administration, deletion, editing | Server management | Out of scope for normal ChannelOS; avoid destructive administrative API calls |

### Important distinction

Connecting Jellyfin does not automatically give ChannelOS every Jellyfin client
feature. It gives ChannelOS APIs and streams from which selected features can be built.
Each adopted capability needs a ChannelOS-owned presentation, policy, failure mode, and
test.

---

## 6. Target architecture

```text
                         ChannelOS UI
                   Live / Guide / Library
                              |
                  ChannelOS service boundary
                              |
          +-------------------+-------------------+
          |                                       |
   Channel Runtime                         On Demand Session
          |                                       |
          +-------------------+-------------------+
                              |
                  Media Catalog / Identity
                              |
             +----------------+----------------+
             |                                 |
      Local Source Adapter              Jellyfin Source Adapter
      paths + scan + ffprobe             REST + images + cache
             |                                 |
             +----------------+----------------+
                              |
                    Playback Resolver
                              |
             +----------------+----------------+
             |                                 |
       Local playback target            Jellyfin playback target
       file path / libVLC                Direct Play or transcode
```

### 6.1 Proposed interfaces

Names are provisional, but the responsibilities should remain distinct.

#### `MediaSourceAdapter`

Responsible for discovery and metadata projection.

```python
class MediaSourceAdapter(Protocol):
    source_id: str
    source_kind: str

    def health(self) -> SourceHealth: ...
    def sync(self, cursor: str | None = None) -> SourceSyncResult: ...
    def browse(self, query: BrowseQuery) -> Page[CatalogItem]: ...
    def resolve_selector(self, selector: SourceSelector) -> tuple[str, ...]: ...
```

Implementations:

- `LocalMediaSourceAdapter` wraps the existing `MediaScanner` / `MediaLibrary` path;
- `JellyfinMediaSourceAdapter` calls Jellyfin and maintains a local projection cache.

#### `PlaybackResolver`

Responsible for selecting a usable location and creating a playback target.

```python
class PlaybackResolver(Protocol):
    def resolve(
        self,
        asset_id: str,
        *,
        start_seconds: float,
        capabilities: PlaybackCapabilities,
    ) -> PlaybackTarget: ...
```

#### `PlaybackTarget`

Replaces the assumption that a backend always loads a local path.

```text
PlaybackTarget
    kind: local_file | http_stream | hls
    locator: path or ephemeral URL
    headers/options: secret-bearing, memory-only
    source_id
    source_kind
    media_source_id
    play_session_id
    play_method: direct_play | remux | direct_stream | transcode
    seekable
    expires_at (when applicable)
```

The scheduling engine does not need these fields. It continues to schedule stable
catalog identity and duration. Playback resolution happens only when a program is
tuned or selected On Demand.

#### `PlaybackReporter`

Optional provider hook for start/progress/stop events. Jellyfin uses it to maintain
server sessions and user watch state; local playback can use a no-op implementation.

### 6.2 Why one giant `JellyfinPlaybackBackend` is not enough

A decoder backend controls media playback after a target exists. Jellyfin also needs:

- authentication;
- item discovery;
- metadata caching;
- artwork caching;
- playback-info negotiation;
- version and track selection;
- stream lifecycle and progress reporting;
- server health and reconnect behavior.

Those responsibilities belong around the playback boundary, not inside the decoder
class and not inside QML.

---

## 7. Media identity and catalog model

### 7.1 Preserve the current asset/location distinction

The existing principle remains correct:

> **A media asset is not its path.**

The generalized form is:

> **A media asset is not any one provider location.**

### 7.2 Proposed catalog records

```text
CatalogAsset
    asset_id                    ChannelOS-stable identity
    identity_confidence
    media_type
    duration_seconds
    preferred_title
    metadata_revision

CatalogLocation
    location_id
    asset_id
    source_kind                 local | jellyfin
    source_id                   local root or server UUID
    provider_item_id            Jellyfin item ID when applicable
    local_path                  nullable
    availability
    last_verified_at

CatalogMetadata
    asset_id
    title / sort_title / original_title
    series / season / episode
    overview / year / rating
    genres / tags / people / studios
    provider_ids
    provenance and user overrides

CatalogImage
    asset_id
    source_id
    image_type
    provider_tag
    local_cache_path
```

### 7.3 Remote identity

Until content equivalence is established, a Jellyfin item receives a source-scoped
stable reference such as:

```text
jellyfin:<server-uuid>:<item-id>
```

This is stable enough for a channel schedule tied to that server but is not proof that
the item equals a local file or an item on another server.

### 7.4 Local/remote reconciliation

Potential evidence, strongest first:

1. explicit user confirmation;
2. exact content hash made available by both locations;
3. a trusted sidecar or ChannelOS export carrying the same ChannelOS asset ID;
4. strong provider identity plus matching edition, duration, and technical evidence.

Title-only matching is never sufficient for automatic merging.

When equivalence is trusted, one `CatalogAsset` may have both local and Jellyfin
locations. Local-first playback can then be applied safely.

---

## 8. Channel definitions and source selectors

Schema `0.1` supports only:

```yaml
sources:
  - path: D:\Media\Shows
```

Remote sources require a new explicitly versioned schema. A possible future shape is:

```yaml
schema_version: "0.2"
channel: 42
name: Server Sci-Fi
sources:
  - kind: jellyfin
    server: home-server
    library_id: "..."
    filters:
      genres: [Science Fiction]
      media_types: [Movie, Episode]
programming:
  mode: shuffle
```

Portable channel definitions may contain a non-secret server alias and provider item
IDs. They must never contain tokens, passwords, or raw authenticated URLs.

### Initial scope recommendation

The first inbound proof should avoid changing portable YAML immediately. It can create
one temporary Jellyfin-backed channel from a selected Jellyfin library through local
development configuration. Schema `0.2` should be accepted only after the identity,
offline, and export semantics are tested.

---

## 9. Guide and couch experience

The Guide must communicate source quality without turning into a server dashboard.

### 9.1 Default Guide grouping

The initial design should group channels by playback source affinity:

```text
LOCAL CHANNELS
  001  ChannelOS
  007  Sci-Fi
  012  Cartoons

JELLYFIN — HOME SERVER
  101  Server Movies
  112  Archive Television
```

This divider gives the viewer an immediate expectation:

- rows above it should tune with local-file smoothness;
- rows below it depend on the named server and network.

The divider is a presentation projection over channel/source metadata. It must not
split or recalculate the runtime schedule.

### 9.2 Source affinity

For the first implementation, a channel should be one of:

- `local` — all scheduled items resolve locally;
- `jellyfin:<server-id>` — items are expected from one server;
- `hybrid` — explicitly configured and deferred until source switching is tested.

Avoid automatic mixed local/server channels in the first release. A channel that
changes transport every program can make tuning behavior unpredictable and obscure
failure causes.

### 9.3 Program and channel indicators

Use restrained indicators rather than warning banners:

- local disk/home icon for local rows;
- server icon plus configured server name for Jellyfin rows;
- dimmed row and `SERVER OFFLINE` when unavailable;
- optional playback-method text in Info: `LOCAL`, `DIRECT PLAY`, or `TRANSCODING`;
- do not expose raw URLs, tokens, or API vocabulary in the couch UI.

### 9.4 Offline behavior

If a server goes offline:

- its rows remain in their stable Guide positions;
- cached titles and artwork remain visible;
- programs are marked unavailable;
- the Broadcast Clock continues mathematically;
- tuning shows a ChannelOS-styled recovery screen with retry/back options;
- Channel Up/Down can continue to the next channel;
- the schedule is not silently compressed, skipped, or re-anchored.

This preserves the truth that a broadcast can be scheduled even when its physical
source is temporarily unavailable.

---

## 10. Library experience

Jellyfin-backed media should appear inside ChannelOS's existing Library rather than in
a separate embedded web page.

### 10.1 Top-level presentation

ChannelOS may expose unified shelves with source filters:

- All Media;
- Local;
- one entry per connected Jellyfin server;
- Movies;
- Television;
- Continue Watching;
- Recently Added;
- Favorites;
- Collections;
- Genres and tags.

Every item retains source provenance even when shown in a unified shelf.

### 10.2 Cached projection for smoothness

Routine browsing should not wait for a Jellyfin request for every card. ChannelOS
should cache the metadata and artwork required for its own shelves and refresh in the
background.

The official Jellyfin-for-Kodi integration demonstrates the same useful tradeoff:
locally synchronized metadata feels like a native local UI, while dynamic server
browsing adds visible request latency. ChannelOS should use a bounded local projection
cache while avoiding Kodi's mistake of letting the synchronized server database
consume or conflict with unrelated local library identity.

### 10.3 Metadata authority

Suggested precedence:

1. explicit ChannelOS user override;
2. durable local ChannelOS metadata;
3. current Jellyfin metadata for that provider location;
4. filename/path fallback.

Refreshing Jellyfin metadata must not erase a ChannelOS user correction.

---

## 11. Connection and authentication

### 11.1 Setup flow

Inside ChannelOS Settings or Library Manager:

1. **Add Media Source**
2. **Jellyfin Server**
3. discover on LAN or enter a URL manually;
4. verify `/System/Info/Public` and record server UUID/name/version;
5. connect using Quick Connect when enabled, otherwise username/password;
6. store the returned device access token securely;
7. choose visible Jellyfin libraries;
8. perform initial metadata sync;
9. return to ChannelOS Library.

The Jellyfin web dashboard remains available for Jellyfin administration, but it is
not part of routine ChannelOS viewing.

### 11.2 Connection record

Non-secret settings may include:

```text
server alias
base URL
server UUID
server version
user ID / display name
selected library IDs
TLS policy
sync cursor / last successful sync
source affinity preferences
```

The token is stored separately in a credential vault.

### 11.3 Compatibility handshake

On connection and periodically thereafter:

- request public server info;
- confirm the server UUID matches the configured connection;
- record the version;
- test authenticated user info and visible views;
- detect HTTP 401, 403, 503, timeouts, and version incompatibility separately;
- never treat a restart/503 as an empty library sync.

---

## 12. Synchronization strategy

### Phase-one sync

1. fetch user views/libraries;
2. page through selected video items;
3. request only fields needed for the initial catalog projection;
4. upsert provider locations and metadata in one transaction/batch;
5. mark missing remote items unavailable only after a complete successful sync;
6. download/cache selected artwork lazily;
7. preserve the previous cache if the sync fails or is cancelled.

This mirrors the existing safe local-scan rule: incomplete discovery must not make
previously known media disappear.

### Incremental sync

After full sync is reliable:

- use server modification timestamps/cursors where trustworthy;
- optionally use WebSocket notifications or the Kodi Sync Queue plugin as an
  acceleration path;
- retain periodic reconciliation as the correctness fallback;
- debounce bursts from server library scans;
- keep all network work off the QML/UI thread.

### Cache layers

- **Catalog cache:** durable metadata required for Guide and Library;
- **Artwork cache:** bounded, replaceable presentation cache;
- **Playback negotiation cache:** short-lived only;
- **Media cache/download:** no automatic cache; future explicit user feature.

---

## 13. Playback strategy

### 13.1 Selection order

For a selected `CatalogAsset`:

1. use a verified online local location when policy allows;
2. otherwise ask the appropriate Jellyfin server for playback information;
3. prefer Direct Play when compatible and reachable;
4. allow remux/direct stream when needed;
5. allow transcoding within the user's quality and server policy;
6. fail visibly without changing schedule truth if no target is usable.

### 13.2 Device profile

ChannelOS must describe its actual playback capabilities rather than claiming support
for every format. The profile should reflect:

- libVLC/container/codec support in the packaged runtime;
- platform hardware-decoding reality;
- supported stream protocols;
- subtitle formats and burn-in requirements;
- maximum configured bitrate/resolution;
- audio channel and codec support.

An inaccurate profile produces unnecessary transcoding or playback failures.

### 13.3 Authentication transport

Ordinary API requests should use Jellyfin's authorization header with a device token.
Playback URLs and decoder logs require special care because some Jellyfin deployments
use query-string API keys.

Preferred long-term approach:

- ChannelOS creates a loopback-only authenticated stream relay;
- libVLC receives an uncredentialed ephemeral localhost URL;
- the relay injects the Jellyfin authorization header upstream;
- the relay never logs full upstream URLs or tokens.

A first proof may use a short-lived authenticated URL only if logging is scrubbed and
the URL is never persisted.

### 13.4 Broadcast Clock seeking

Jellyfin playback negotiation must accept the offset selected by ChannelOS.

```text
Broadcast Clock -> asset + offset
                     |
                     v
            Jellyfin PlaybackInfo
                     |
                     v
        resolved stream beginning at offset
```

Jellyfin must not choose the program or infer the channel position. It only delivers
the item ChannelOS selected.

### 13.5 Program transitions

At a ChannelOS program boundary:

- resolve the next scheduled asset;
- close/report the previous Jellyfin playback session;
- negotiate the next target;
- begin the next item at the ChannelOS-selected offset;
- preserve the Viewer Clock even if network startup introduces delay.

Future optimization may pre-negotiate the next server item shortly before a boundary,
but must not decode every channel or let prefetch state become schedule authority.

---

## 14. Watch state, favorites, and profiles

These systems overlap but should not be merged casually.

### 14.1 Recommended first policy

- ChannelOS remains authoritative for ChannelOS Broadcast/Viewer clocks;
- ChannelOS remains authoritative for local On Demand watch state;
- Jellyfin playback is reported to Jellyfin for session correctness;
- two-way resume/favorite synchronization is opt-in and deferred until conflicts are
  specified and tested.

### 14.2 Why channel viewing is different

Watching ten minutes in the middle of a scheduled ChannelOS broadcast is not the same
intent as deliberately watching an episode On Demand. Automatically marking that item
complete in Jellyfin could pollute Continue Watching and play counts.

The eventual policy should distinguish:

- `channel_live`;
- `channel_timeshifted`;
- `watch_from_beginning`;
- `on_demand`.

Only explicit On Demand viewing should participate in ordinary Jellyfin resume state by
default. Other modes require deliberate rules.

### 14.3 Profile mapping

A ChannelOS profile may optionally map to one Jellyfin user per server. That mapping
controls only the Jellyfin content and user data visible through that connection.

ChannelOS local profiles and permissions remain valid when the server is absent.

---

## 15. Performance and responsiveness

The user-visible reason to distinguish local and server media is real: server access
adds network, authentication, negotiation, and possibly transcoding latency.

### Required performance behaviors

- never block the QML thread on network I/O;
- populate Guide/Library from local projection caches;
- lazy-load higher-resolution artwork;
- keep health checks short and cancellable;
- reuse HTTP connections;
- page large libraries;
- request only required Jellyfin fields;
- limit concurrent image downloads and playback negotiations;
- pre-negotiate only the actively viewed/tuned context;
- expose server-backed rows clearly so a slower tune is understandable;
- measure tune-to-first-frame separately for local, Direct Play, and transcode.

### Suggested initial budgets

These are engineering targets, not guarantees:

- cached Guide open: no network dependency;
- cached Library shelf: immediate first paint;
- server health timeout: short enough not to stall navigation;
- local tune: preserve current behavior;
- Jellyfin Direct Play tune: measure and optimize after the first proof;
- transcode tune: display a calm loading state rather than freezing the interface.

---

## 16. Security and trust model

- Treat the configured server as a remote system even when it is `127.0.0.1`.
- Validate schemes and origins; prefer HTTPS for non-loopback remote servers.
- Never follow an authentication-bearing redirect to a different origin.
- Enforce timeouts and bounded response sizes for metadata.
- Stream large media rather than buffering it in Python memory.
- Sanitize filenames, titles, and remote text before use in paths or logs.
- Keep cached artwork and metadata separate from user media.
- Do not offer Jellyfin deletion or administrative controls in the first integration.
- Respect the authenticated user's Jellyfin library access and parental restrictions.
- Do not expose the ChannelOS local relay beyond loopback.

---

## 17. Dependency and licensing posture

ChannelOS is MPL-2.0. The maintained `jellyfin-apiclient-python` project is useful as a
reference and demonstrates common client flows, but it is GPL-3.0 and explicitly notes
that its API coverage is incomplete.

The preferred initial implementation is therefore a small ChannelOS-owned REST client
behind a narrow protocol boundary, using a dependency with a compatible license or the
Python standard library. Do not vendor Jellyfin client code into ChannelOS without a
specific license review.

Jellyfin names, trademarks, code, and documentation retain their own terms. Add any
shipped dependency to `THIRD_PARTY_NOTICES.md` and credit/reference Jellyfin in
`ACKNOWLEDGMENTS.md` without implying official endorsement.

---

## 18. API surface expected for the first client

Exact request/response compatibility must be tested against the supported server
versions. The 10.11.11 source exposes the relevant families:

| Purpose | Jellyfin API family |
|---|---|
| Server identity/readiness | `System/Info/Public`, `System/Ping`, authenticated system/endpoint info |
| Authentication | `Users/AuthenticateByName`, Quick Connect endpoints, device access token |
| User libraries | `UserViews` |
| Item browse/search/filter | `Items` with user, parent, type, field, paging, filter, and sort parameters |
| Item details | user-aware item lookup and requested metadata fields |
| Artwork | `Items/{itemId}/Images/{imageType}` |
| Playback negotiation | `Items/{itemId}/PlaybackInfo` (POST preferred for a device profile) |
| Video delivery | video stream / HLS routes returned or described by playback negotiation |
| Watch/session reporting | `Sessions/Playing`, progress, ping, and stopped |
| Continue Watching / latest / favorites | user-aware item queries and filters |
| Live update acceleration | WebSocket session notifications; optional sync plugin path later |

The code should not scatter literal endpoints across UI classes. One tested
`JellyfinClient` boundary owns request construction, authentication, response parsing,
version workarounds, and redaction.

---

## 19. Implementation phases

### Phase 0 — Correct the direction and prove the server client

Deliverables:

- this master plan;
- mark the outbound M3U/XMLTV adapter as an optional/legacy proof, not product direction;
- a read-only `JellyfinClient` with mocked HTTP tests;
- connect to one server and retrieve public info;
- authenticate one user;
- list selected user libraries and a small page of video items;
- no QML changes and no playback yet.

Exit gate:

> A source-tree command can identify the configured 10.11.11 server and print a
> redacted, typed summary of the user's visible video libraries and several items.

### Phase 1 — Local projection cache

Deliverables:

- provider-neutral catalog/location schema;
- Jellyfin server and item reference tables;
- transactional full sync with cancellation and failure safety;
- cached titles, durations, hierarchy, genres/tags, and image references;
- local and remote source provenance;
- tests proving a failed sync cannot erase the previous projection.

Exit gate:

> ChannelOS can restart with Jellyfin offline and still render cached remote library
> shelves and Guide labels while clearly showing that playback is unavailable.

### Phase 2 — ChannelOS Library integration

Deliverables:

- connect/remove/resync UI in ChannelOS Settings or Library Manager;
- server shelves inside the ChannelOS Library;
- posters/backdrops from the ChannelOS artwork cache;
- search/browse and `Add to Channel` using provider-neutral asset references;
- no embedded Jellyfin web page;
- no terminal, manual URL, helper-console, or separate-adapter workflow for ordinary users.

Exit gate:

> The viewer can browse server media, inspect it, and add it to ChannelOS programming
> without leaving the ChannelOS interface.

### Phase 3 — On Demand playback

Deliverables:

- `PlaybackTarget` and `PlaybackResolver` abstractions;
- Jellyfin PlaybackInfo negotiation;
- Direct Play first, then remux/transcode fallback;
- secure token transport/redacted logging;
- audio/subtitle selection at a minimal useful level;
- start/progress/stop reporting;
- local playback remains unchanged.

Exit gate:

> One server item plays inside the existing ChannelOS video surface, seeks correctly,
> and stops cleanly while local On Demand playback still passes its full test suite.

### Phase 4 — Server-backed television channels

Deliverables:

- versioned remote channel source selectors;
- stable Jellyfin item identities in schedule signatures;
- server-backed ChannelRuntime construction;
- Broadcast Clock offset passed into Jellyfin playback;
- clean program transitions;
- local/server Guide divider and source indicators;
- offline rows that preserve schedule truth.

Exit gate:

> A Jellyfin-backed ChannelOS channel survives ChannelOS restart, tunes to the exact
> program and offset predicted by the Guide, crosses a program boundary, and fails
> honestly when the server is stopped.

### Phase 5 — Hybrid intelligence and household polish

Possible work:

- verified local/server duplicate reconciliation;
- local-first fallback for equivalent items;
- optional watch-state/favorite synchronization;
- profile-to-Jellyfin-user mapping;
- multiple servers;
- WebSocket/incremental synchronization;
- chapters, media segments, richer stream selection;
- explicit offline downloads;
- optional remote clients/casting/session integrations.

---

## 20. Test strategy

### Unit tests

- URL normalization and same-origin validation;
- auth header creation and mandatory redaction;
- DTO parsing with missing/unknown Jellyfin fields;
- paging and cancellation;
- provider-scoped identity stability;
- local-first location selection;
- no title-only automatic merges;
- cache transaction rollback;
- server-offline state transitions;
- PlaybackInfo method selection;
- progress reporting mode distinctions;
- Guide grouping without schedule mutation.

### Contract tests

- recorded sanitized 10.11.11 responses;
- a disposable Jellyfin test server where practical;
- public info, authentication, views, items, images, PlaybackInfo, stream, progress;
- 401 token expiry, 403 restriction, 404 item removal, 503 startup/restart;
- slow responses, connection reset, malformed JSON, and version changes.

### Real-machine gates

1. same-PC Jellyfin at `127.0.0.1:8096`;
2. ChannelOS local media still playing directly;
3. one cached Jellyfin library visible in ChannelOS;
4. one Jellyfin item playing On Demand inside ChannelOS;
5. one Jellyfin-backed channel tuning at a non-zero Broadcast Clock offset;
6. server stopped during browsing;
7. server stopped during playback;
8. restart and reconnect without duplicate catalog items;
9. confirm no token appears in logs, YAML, SQLite diagnostic exports, or UI errors;
10. repeat the complete packaged setup on Windows without opening a terminal or manually entering an API route.

### Regression rule

Every phase must run the existing ChannelOS suite. Jellyfin support is not successful
if it weakens local playback, local scanning, portable channel definitions, or couch
navigation.

---

## 21. Explicit non-goals for the first implementation

- rewriting ChannelOS in C#;
- embedding or reskinning Jellyfin Web;
- making Jellyfin mandatory;
- making a Jellyfin plugin the ChannelOS core;
- replacing ChannelOS Guide truth with Jellyfin Live TV;
- importing Jellyfin playlists as channels without user intent;
- exposing server administration or media deletion;
- silently copying an entire server library locally;
- automatically merging media by title;
- supporting every Jellyfin media type before video works correctly;
- promising every Jellyfin client feature in ChannelOS merely because the API exists.

---

## 22. Treatment of the existing outbound adapter

The current `src/channelos/jellyfin.py` adapter proves that ChannelOS schedules can be
represented as M3U, XMLTV, and MPEG-TS. That is real interoperability work, but it is
the opposite product direction from this plan.

Recommended treatment:

- retain it temporarily as an experimental outbound adapter;
- rename documentation and CLI descriptions so its direction is unmistakable;
- do not build the inbound integration on top of its HTTP server;
- do not let its FFmpeg streaming path become ChannelOS playback architecture;
- decide later whether outbound Jellyfin Live TV remains a supported optional feature.

Nothing in this master plan requires deleting that proof. It simply stops treating the
proof as the primary Jellyfin product direction.

---

## 23. Immediate next engineering slice

The safest first code change is deliberately small:

1. add a `channelos/jellyfin_client.py` protocol/client module;
2. add typed server, user-view, and item summary records;
3. implement public-info, authentication, user-views, and paged-video-items requests;
4. redact tokens centrally;
5. test using an injected fake HTTP transport;
6. expose a development-only CLI inspection command;
7. run it against the already installed local Jellyfin 10.11.11 server;
8. make no library schema, QML, channel YAML, or playback changes yet.

That slice proves the correct direction:

```text
Jellyfin -> ChannelOS
```

before the permanent catalog and playback migrations begin.

---

## 24. Open design decisions

These should be decided with prototypes and measurements rather than guessed now:

1. whether initial authentication uses Quick Connect or username/password first;
2. the compatible HTTP dependency and secure Windows credential storage mechanism;
3. whether ChannelOS retains SHA-256 as one identity type or introduces a new root
   `CatalogAsset` ID above content identities;
4. the minimum reliable evidence for automatic local/Jellyfin equivalence;
5. the exact Guide divider visual and remote-focus behavior;
6. whether remote channels may mix sources in schema `0.2` or wait for a later schema;
7. which libVLC capabilities should be advertised to Jellyfin;
8. whether the first stream path uses an ephemeral query token or loopback relay;
9. which Jellyfin watch events should be reported for live/channel viewing;
10. supported Jellyfin server-version range after 10.11.11 contract testing.

---

## 25. Reference baseline

ChannelOS references:

- `docs/MASTER_DESIGN.md`
- `docs/ARCHITECTURE.md`
- `docs/GUIDE_AND_UI_BOUNDARY.md`
- `docs/decisions/0001-local-first-portable-core.md`
- `docs/decisions/0002-media-identity-and-playback.md`
- `docs/decisions/0003-persistent-channel-clocks.md`
- `src/channelos/library.py`
- `src/channelos/scanner.py`
- `src/channelos/resolve.py`
- `src/channelos/runtime.py`
- `src/channelos/guide.py`
- `src/channelos/playback.py`
- `src/channelos/television.py`
- `src/channelos/on_demand.py`

Jellyfin primary references reviewed:

- [Jellyfin documentation](https://jellyfin.org/docs/)
- [Libraries](https://jellyfin.org/docs/general/server/libraries/)
- [Metadata](https://jellyfin.org/docs/general/server/metadata/)
- [Transcoding](https://jellyfin.org/docs/general/post-install/transcoding/)
- [Managing users](https://jellyfin.org/docs/general/server/users/adding-managing-users/)
- [Quick Connect](https://jellyfin.org/docs/general/server/quick-connect/)
- [Networking](https://jellyfin.org/docs/general/post-install/networking/)
- [Jellyfin for Kodi](https://jellyfin.org/docs/general/clients/kodi/)
- [Server 10.11.11 source](https://github.com/jellyfin/jellyfin/tree/v10.11.11)
- [Jellyfin Python API client](https://github.com/jellyfin/jellyfin-apiclient-python)

Jellyfin is fast-moving. Source and API behavior must be rechecked when the supported
version range changes.

---

## 26. Final architectural statement

```text
Jellyfin may know where remote media lives.
Jellyfin may know how to describe and deliver it.

ChannelOS decides what channel it belongs to.
ChannelOS decides when it airs.
ChannelOS decides what the viewer sees.
ChannelOS remains the television.
```
