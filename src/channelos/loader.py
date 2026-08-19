from __future__ import annotations

from pathlib import Path

import yaml

from .models import ChannelDefinition, ChannelValidationError


def load_channel(path: str | Path) -> ChannelDefinition:
    channel_path = Path(path)
    try:
        text = channel_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ChannelValidationError(f"could not read {channel_path}: {exc}") from exc

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ChannelValidationError(f"invalid YAML in {channel_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ChannelValidationError("channel file must contain a top-level mapping")

    return ChannelDefinition.from_mapping(raw)
