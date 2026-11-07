"""Custom themes: a few role colours plus an optional wallpaper.

Every QML colour is written as ``Theme.c("#original")`` against the ChannelOS
dark palette. A custom theme names about a dozen *roles* (background, panels,
text, accent...). :func:`derive_palette` maps each original colour to a role
blend, so one choice of roles restyles every screen consistently, light or
dark. Themes and their images are stored beside the settings file, so they
travel with a portable setup.
"""
from __future__ import annotations

import colorsys
import json
import re
import shutil
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

ROLE_NAMES = (
    "background", "surface", "raised", "line", "text", "mutedText",
    "accent", "highlight", "selection", "live", "success", "warning",
)
ROLE_LABELS = {
    "background": "Background", "surface": "Panels", "raised": "Buttons & cards",
    "line": "Borders", "text": "Text", "mutedText": "Secondary text",
    "accent": "Accent", "highlight": "Highlight & focus", "selection": "Selection",
    "live": "Live & alerts", "success": "Success", "warning": "Warning",
}
CHANNELOS_ROLES = {
    "background": "#050c15", "surface": "#081625", "raised": "#0d2035", "line": "#1a3550",
    "text": "#f4f7fb", "mutedText": "#9fb0c2", "accent": "#1a91ff", "highlight": "#42adff",
    "selection": "#12396a", "live": "#ff4a4a", "success": "#2bcf75", "warning": "#ffb84a",
}
CHROMESPACE_ROLES = {
    "background": "#e8ebf0", "surface": "#ffffff", "raised": "#f5f7fa", "line": "#c5d0de",
    "text": "#1b2540", "mutedText": "#5b6678", "accent": "#1d4fa8", "highlight": "#ec6a12",
    "selection": "#d6e4f5", "live": "#d93025", "success": "#1e8e3e", "warning": "#c26401",
}
ROLE_HINTS = {
    "background": "Behind everything, around the panels",
    "surface": "Sidebars, cards and list rows",
    "raised": "Buttons, fields and Guide program blocks",
    "line": "Outlines and dividers",
    "text": "Titles and most writing",
    "mutedText": "Descriptions and hints",
    "accent": "Main buttons such as Apply and Save",
    "highlight": "What is selected now: focus rings, values",
    "selection": "Fill behind selected rows and on/off buttons",
    "live": "LIVE badges, errors and delete buttons",
    "success": "Ready, on air and in-use badges",
    "warning": "Unsaved changes and cautions",
}
PRESETS = {"channelos": CHANNELOS_ROLES, "chromespace": CHROMESPACE_ROLES}
WALLPAPER_FITS = ("fill", "fit", "tile", "center")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
CUSTOM_PREFIX = "custom-"
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_LITERAL = re.compile(r'Theme\.c\("(#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?)"\)')


def _rgb(hex_color: str) -> tuple[float, float, float]:
    value = hex_color[-6:]
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _hex(rgb: tuple[float, float, float], alpha: str | None = None) -> str:
    text = "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in rgb)
    return f"#{alpha}{text}" if alpha else f"#{text}"


def _mix(a: str, b: str, t: float) -> tuple[float, float, float]:
    t = max(0.0, min(1.0, t))
    ra, rb = _rgb(a), _rgb(b)
    return tuple(x + (y - x) * t for x, y in zip(ra, rb, strict=True))  # type: ignore[return-value]


def _luminance(hex_color: str) -> float:
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in _rgb(hex_color)]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def readable_on(background: str, preferred: str) -> str:
    """``preferred`` when it reads on ``background``, else white or black."""
    if contrast(preferred, background) >= 4.5:
        return preferred
    return "#ffffff" if contrast("#ffffff", background) >= contrast("#000000", background) else "#000000"


# ChannelOS surface anchors by lightness: (original, role or role blend).
_SURFACES = (("#050c15", "background"), ("#081625", "surface"), ("#0d2035", "raised"),
             ("#10283f", "soft"), ("#1a3550", "line"))


def _role_color(roles: Mapping[str, str], key: str) -> str:
    if key == "soft":
        return _hex(_mix(roles["raised"], roles["selection"], 0.5))
    return roles[key]


def _derive(original: str, roles: Mapping[str, str]) -> str:
    alpha = original[1:3] if len(original) == 9 else None
    base = "#" + original[-6:].lower()
    r, g, b = _rgb(base)
    hue, light, _sat = colorsys.rgb_to_hls(r, g, b)
    # Chroma, not HLS saturation: near-white and near-black colours report
    # high saturation even when they read as neutral.
    chroma = max(r, g, b) - min(r, g, b)
    degrees = hue * 360
    warm, green = degrees < 60 or degrees > 330, 80 < degrees < 170
    red = degrees < 20 or degrees > 330
    if base == "#000000":
        return original
    if base == "#ffffff":  # text on accent fills
        return _hex(_rgb(readable_on(roles["accent"], "#ffffff")), alpha)
    if base == "#fffffe":  # text on checked / focused controls
        return _hex(_rgb(readable_on(roles["selection"], roles["text"])), alpha)
    if light < 0.32:
        if chroma > 0.12 and (warm or green):
            tint = roles["success"] if green else roles["live"] if red else roles["warning"]
            return _hex(_mix(roles["surface"], tint, 0.22), alpha)
        if chroma > 0.25 and light > 0.12:  # selection / focus tints
            return _hex(_mix(roles["selection"], roles["accent"], max(0.0, light - 0.2) * 3), alpha)
        anchors = [(colorsys.rgb_to_hls(*_rgb(o))[1], _role_color(roles, k)) for o, k in _SURFACES]
        if light <= anchors[0][0]:
            return _hex(_rgb(anchors[0][1]), alpha)
        for (l0, c0), (l1, c1) in zip(anchors, anchors[1:], strict=False):
            if light <= l1:
                return _hex(_mix(c0, c1, (light - l0) / (l1 - l0)), alpha)
        return _hex(_mix(roles["line"], roles["mutedText"], (light - anchors[-1][0]) / 0.3), alpha)
    if chroma > 0.25:
        if green:
            return _hex(_rgb(roles["success"]), alpha)
        if red:
            return _hex(_rgb(roles["live"]), alpha)
        if warm:
            return _hex(_rgb(roles["warning"]), alpha)
        if light > 0.6:
            return _hex(_rgb(roles["highlight"]), alpha)
        return _hex(_mix(roles["accent"], roles["background"], max(0.0, 0.5 - light) * 0.6), alpha)
    # Neutral text greys: ChannelOS secondary text sits at L 0.69, text at 0.97.
    muted_light, text_light = 0.692, 0.97
    if light >= text_light:
        return _hex(_rgb(roles["text"]), alpha)
    if light >= muted_light:
        return _hex(_mix(roles["mutedText"], roles["text"], (light - muted_light) / (text_light - muted_light)), alpha)
    return _hex(_mix(roles["line"], roles["mutedText"], (light - 0.32) / (muted_light - 0.32)), alpha)


@lru_cache(maxsize=1)
def theme_literals(qml_dir: str | None = None) -> tuple[str, ...]:
    """Every colour the QML screens pass to ``Theme.c``."""
    directory = Path(qml_dir) if qml_dir else Path(__file__).resolve().parent / "qml"
    found = {"#ffffff", "#fffffe"}
    for path in directory.glob("*.qml"):
        if path.name != "Theme.qml":
            found |= {m.lower() for m in _LITERAL.findall(path.read_text(encoding="utf-8"))}
    return tuple(sorted(found))


def derive_palette(roles: Mapping[str, str], *, panel_opacity: int = 100) -> dict[str, str]:
    """Map every ChannelOS colour to this theme. Panels may be translucent so
    a wallpaper shows through (opacity applies to surface colours only)."""
    complete = normalise_roles(roles)
    palette = {}
    alpha = None if panel_opacity >= 100 else f"{round(max(0, panel_opacity) * 255 / 100):02x}"
    for original in theme_literals():
        mapped = _derive(original, complete)
        base_light = colorsys.rgb_to_hls(*_rgb(original))[1]
        # The background stays opaque: ThemeBackdrop paints it under the image.
        if alpha and len(original) == 7 and base_light < 0.2 and original not in {"#000000", "#050c15"}:
            mapped = "#" + alpha + mapped[-6:]
        palette[original] = mapped
    return palette


def normalise_roles(roles: Mapping[str, Any]) -> dict[str, str]:
    complete = dict(CHANNELOS_ROLES)
    for name in ROLE_NAMES:
        value = str(roles.get(name, "") or "").strip()
        if _HEX.match(value):
            complete[name] = value.lower()
    return complete


@dataclass
class CustomTheme:
    theme_id: str
    name: str
    roles: dict[str, str]
    wallpaper: str = ""          # file name inside the themes folder
    wallpaper_fit: str = "fill"
    wallpaper_opacity: int = 100
    panel_opacity: int = 100
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "CustomTheme":
        theme_id = str(raw.get("id") or "")
        if not theme_id.startswith(CUSTOM_PREFIX):
            theme_id = CUSTOM_PREFIX + uuid.uuid4().hex[:10]
        fit = str(raw.get("wallpaperFit", "fill"))
        return cls(
            theme_id=theme_id,
            name=(str(raw.get("name") or "My Theme").strip() or "My Theme")[:40],
            roles=normalise_roles(raw.get("roles") or {}),
            wallpaper=Path(str(raw.get("wallpaper") or "")).name,
            wallpaper_fit=fit if fit in WALLPAPER_FITS else "fill",
            wallpaper_opacity=_percent(raw.get("wallpaperOpacity"), 100, 10),
            panel_opacity=_percent(raw.get("panelOpacity"), 100, 40),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {"id": self.theme_id, "name": self.name, "roles": dict(self.roles),
                "wallpaper": self.wallpaper, "wallpaperFit": self.wallpaper_fit,
                "wallpaperOpacity": self.wallpaper_opacity, "panelOpacity": self.panel_opacity}


def _percent(value: Any, default: int, minimum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(100, number))


class ThemeStore:
    """Custom themes in ``<setup>/themes/themes.json`` with their images."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.path = self.directory / "themes.json"

    def load(self) -> list[CustomTheme]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []
        items = raw.get("themes", []) if isinstance(raw, dict) else []
        themes, seen = [], set()
        for item in items:
            if isinstance(item, dict):
                theme = CustomTheme.from_mapping(item)
                if theme.theme_id not in seen:
                    seen.add(theme.theme_id)
                    themes.append(theme)
        return themes

    def _write(self, themes: list[CustomTheme]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name("themes.json.tmp")
        temporary.write_text(json.dumps({"version": 1, "themes": [t.to_mapping() for t in themes]},
                                        indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def save(self, raw: Mapping[str, Any]) -> CustomTheme:
        theme = CustomTheme.from_mapping(raw)
        themes = [t for t in self.load() if t.theme_id != theme.theme_id]
        themes.append(theme)
        self._write(themes)
        self._drop_unused_images(themes)
        return theme

    def delete(self, theme_id: str) -> None:
        themes = [t for t in self.load() if t.theme_id != theme_id]
        self._write(themes)
        self._drop_unused_images(themes)

    def get(self, theme_id: str) -> CustomTheme | None:
        return next((t for t in self.load() if t.theme_id == theme_id), None)

    def import_image(self, source: str | Path) -> str:
        """Copy a picture into the themes folder; returns its stored file name."""
        path = Path(source)
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            raise ValueError("Choose a PNG, JPEG, WebP, BMP or GIF image")
        if not path.is_file():
            raise ValueError(f"Image not found: {path}")
        if path.stat().st_size > 40 * 1024 * 1024:
            raise ValueError("That image is over 40 MB. Choose a smaller picture.")
        images = self.directory / "images"
        images.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex[:12]}{path.suffix.lower()}"
        shutil.copyfile(path, images / name)
        return name

    def image_path(self, name: str) -> Path | None:
        if not name:
            return None
        path = self.directory / "images" / Path(name).name
        return path if path.is_file() else None

    def _drop_unused_images(self, themes: list[CustomTheme]) -> None:
        images = self.directory / "images"
        if not images.is_dir():
            return
        used = {t.wallpaper for t in themes}
        for path in images.iterdir():
            # Keep fresh imports for drafts not yet saved (under an hour old).
            if path.name not in used and path.is_file():
                try:
                    import time
                    if time.time() - path.stat().st_mtime > 3600:
                        path.unlink()
                except OSError:
                    pass
