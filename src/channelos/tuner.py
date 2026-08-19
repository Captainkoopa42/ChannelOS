from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .playback import PlaybackBackend
from .resolve import ResolvedChannel


@dataclass(slots=True)
class TuneSession:
    channel: ResolvedChannel
    backend: PlaybackBackend
    paused: bool = False

    def start(self) -> Path:
        item = self.channel.first
        self.backend.load(item.location.path)
        self.backend.play()
        return item.location.path

    def execute(self, command: str) -> str:
        parts = command.strip().lower().split()
        if not parts:
            return ""

        name = parts[0]
        if name == "play":
            self.backend.play()
            self.paused = False
            return "playing"
        if name == "pause":
            self.backend.pause()
            self.paused = True
            return "paused"
        if name == "mute":
            self.backend.set_muted(True)
            return "muted"
        if name == "unmute":
            self.backend.set_muted(False)
            return "unmuted"
        if name == "volume" and len(parts) == 2:
            value = int(parts[1])
            self.backend.set_volume(value)
            return f"volume {value}%"
        if name == "seek" and len(parts) == 2:
            target = float(parts[1])
            self.backend.seek(target)
            return f"position {target:.3f}s"
        if name == "skip" and len(parts) == 2:
            delta = float(parts[1])
            target = max(0.0, self.backend.get_position() + delta)
            self.backend.seek(target)
            return f"position {target:.3f}s"
        if name == "rate" and len(parts) == 2:
            rate = float(parts[1])
            self.backend.set_rate(rate)
            return f"rate {rate:g}x"
        if name == "status":
            return (
                f"position={self.backend.get_position():.3f}s "
                f"volume={self.backend.get_volume()}% muted={self.backend.get_muted()}"
            )
        if name in {"stop", "quit", "exit"}:
            self.backend.stop()
            return "stopped"
        if name == "help":
            return (
                "commands: play, pause, mute, unmute, volume N, seek SECONDS, "
                "skip +/-SECONDS, rate X, status, quit"
            )

        raise ValueError(f"unknown playback command: {command!r}")
