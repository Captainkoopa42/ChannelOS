# Acknowledgments

ChannelOS exists because generations of open-source maintainers chose to make
their work inspectable, reusable, and improvable. Thank you.

In particular, ChannelOS is built and tested with help from:

- **Python and CPython**, the language and runtime underneath the project.
- **Qt and Qt for Python / PySide6**, which make the native couch interface
  possible.
- **VideoLAN and libVLC**, which provide the replaceable reference playback
  engine.
- **python-vlc**, which exposes libVLC cleanly to Python.
- **FFmpeg and ffprobe**, which provide optional media inspection and local
  thumbnail generation during development.
- **PyYAML**, which supports ChannelOS's portable, human-readable channel
  definitions.
- **SQLite**, whose small, dependable local database engine supports the media
  library and persistent television clocks.
- **pytest**, which gives the project a practical safety net while it changes.
- **PyInstaller**, which provides the inspectable one-folder Windows packaging
  foundation used by the development release lane.
- **Mozilla and the MPL community**, for stewarding a practical file-level
  copyleft license for open collaboration.
- **Git, GitHub, and GitHub Actions**, which make the project's history,
  developmental branches, collaboration, and automated checks accessible.

ChannelOS also benefits from public documentation, specifications, issue
reports, examples, and hard-won lessons shared by the broader Python, Qt,
VideoLAN, FFmpeg, home-theater, accessibility, controller, and open-source
communities.

The interface draws on familiar television, DVR, electronic-program-guide,
media-library, and ten-foot-interface conventions. Those common design lessons
help ChannelOS feel understandable from a couch while its implementation and
identity remain its own.

This page expresses gratitude. Legal notices and license obligations are
tracked separately in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and
[`docs/DISTRIBUTION.md`](docs/DISTRIBUTION.md). Mention here does not imply
endorsement of ChannelOS by any named project or contributor.
