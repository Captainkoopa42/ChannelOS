"""Controller families, their on-screen layouts, and remappable bindings.

Every physical controller is read in one *positional* vocabulary (the SDL /
XInput standard): the bottom face button is ``south`` whether it says A, B or
Cross on it. A *family* only decides how the controls are drawn and labelled
in Settings → Controller, so one binding table works for every pad.

Drawings use a 100 x 60 canvas. They are simple ChannelOS diagrams that
identify a controller's layout, not reproductions of any product.
"""
from __future__ import annotations

from typing import Any, Mapping

from .control import ControlIntent

# --- Bindable controls (positional) -------------------------------------------------------------

CONTROL_IDS = (
    "south", "east", "west", "north",
    "dpad_up", "dpad_down", "dpad_left", "dpad_right",
    "left_shoulder", "right_shoulder", "left_trigger", "right_trigger",
    "view", "menu", "guide", "misc",
    "left_stick", "right_stick",
    "rstick_up", "rstick_down", "rstick_left", "rstick_right",
    "paddle1", "paddle2", "paddle3", "paddle4", "touchpad",
)

DEFAULT_BINDINGS: dict[str, str] = {
    "south": "SELECT",
    "east": "BACK",
    "west": "PLAY_PAUSE",
    "north": "INFO",
    "dpad_up": "UP",
    "dpad_down": "DOWN",
    "dpad_left": "LEFT",
    "dpad_right": "RIGHT",
    "left_shoulder": "CHANNEL_DOWN",
    "right_shoulder": "CHANNEL_UP",
    "left_trigger": "SKIP_BACK",
    "right_trigger": "SKIP_FORWARD",
    "view": "GUIDE",
    "menu": "HOME",
    "guide": "NONE",
    "misc": "NONE",
    "left_stick": "GO_LIVE",
    "right_stick": "PREVIOUS_CHANNEL",
    "rstick_up": "VOLUME_UP",
    "rstick_down": "VOLUME_DOWN",
    "rstick_left": "NONE",
    "rstick_right": "NONE",
    "paddle1": "NONE",
    "paddle2": "NONE",
    "paddle3": "NONE",
    "paddle4": "NONE",
    "touchpad": "NONE",
}

# Actions offered by the button and keyboard mappers, in menu order.
ACTIONS: tuple[tuple[str, str], ...] = (
    ("NONE", "Nothing"),
    ("SELECT", "Select / OK"),
    ("BACK", "Back"),
    ("UP", "Up"),
    ("DOWN", "Down"),
    ("LEFT", "Left"),
    ("RIGHT", "Right"),
    ("PLAY_PAUSE", "Play / Pause"),
    ("INFO", "Info"),
    ("GUIDE", "Guide"),
    ("GUIDE_NOW", "Guide: Go to Now"),
    ("HOME", "Home"),
    ("CHANNEL_UP", "Channel Up"),
    ("CHANNEL_DOWN", "Channel Down"),
    ("PREVIOUS_CHANNEL", "Previous Channel"),
    ("GO_LIVE", "Go Live"),
    ("SKIP_BACK", "Skip Back"),
    ("SKIP_FORWARD", "Skip Forward"),
    ("REWIND", "Rewind"),
    ("FAST_FORWARD", "Fast Forward"),
    ("VOLUME_UP", "Volume Up"),
    ("VOLUME_DOWN", "Volume Down"),
    ("MUTE", "Mute"),
    ("LIBRARY", "On Demand"),
    ("CHANNELS", "Channels"),
    ("SETTINGS", "Settings"),
)
ACTION_IDS = tuple(action for action, _ in ACTIONS)
ACTION_LABELS = dict(ACTIONS)


def clean_bindings(raw: Any) -> dict[str, str]:
    """Only known controls and actions; anything else falls back to defaults."""
    if not isinstance(raw, Mapping):
        return {}
    return {str(control): str(action) for control, action in raw.items()
            if control in DEFAULT_BINDINGS and action in ACTION_IDS and DEFAULT_BINDINGS[control] != action}


def effective_bindings(overrides: Mapping[str, str] | None) -> dict[str, ControlIntent | None]:
    merged = dict(DEFAULT_BINDINGS)
    merged.update(clean_bindings(overrides or {}))
    return {control: (None if action == "NONE" else ControlIntent(action)) for control, action in merged.items()}


# --- Keyboard ------------------------------------------------------------------------------------

# Keys that never change: Escape is always Back so nobody can lock themselves out.
FIXED_KEYS = {"Key_Escape": "BACK"}

DEFAULT_KEYS: dict[str, str] = {
    "Key_Up": "UP", "Key_Down": "DOWN", "Key_Left": "LEFT", "Key_Right": "RIGHT",
    "Key_Return": "SELECT", "Key_Enter": "SELECT", "Key_Space": "SELECT",
    "Key_Escape": "BACK",
    "Key_G": "GUIDE", "Key_H": "HOME", "Key_Home": "GUIDE_NOW", "Key_I": "INFO",
    "Key_S": "SETTINGS", "Key_B": "CHANNELS", "Key_A": "ADD_MEDIA_SOURCE",
    "Key_L": "GO_LIVE", "Key_P": "PREVIOUS_CHANNEL",
    "Key_Plus": "VOLUME_UP", "Key_Equal": "VOLUME_UP", "Key_Minus": "VOLUME_DOWN", "Key_M": "MUTE",
    "Key_PageUp": "REWIND", "Key_PageDown": "FAST_FORWARD",
    "Key_Comma": "SKIP_BACK", "Key_Period": "SKIP_FORWARD",
    "Key_MediaTogglePlayPause": "PLAY_PAUSE", "Key_VolumeUp": "VOLUME_UP", "Key_VolumeDown": "VOLUME_DOWN",
    "Key_VolumeMute": "MUTE",
}
KEY_ACTION_IDS = ACTION_IDS + ("ADD_MEDIA_SOURCE",)
ACTION_LABELS["ADD_MEDIA_SOURCE"] = "Add Media Folder"


def clean_key_bindings(raw: Any) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    cleaned: dict[str, str] = {}
    for key, action in raw.items():
        key, action = str(key), str(action)
        if not key.startswith("Key_") or key in FIXED_KEYS or key in {f"Key_{d}" for d in range(10)}:
            continue
        if action not in KEY_ACTION_IDS or DEFAULT_KEYS.get(key, "NONE") == action:
            continue
        cleaned[key] = action
    return cleaned


def key_label(key_name: str) -> str:
    names = {"Key_Return": "Enter", "Key_Enter": "Keypad Enter", "Key_Space": "Space", "Key_Escape": "Esc",
             "Key_PageUp": "Page Up", "Key_PageDown": "Page Down", "Key_Plus": "+", "Key_Equal": "=",
             "Key_Minus": "−", "Key_Comma": ",", "Key_Period": ".", "Key_Up": "↑", "Key_Down": "↓",
             "Key_Left": "←", "Key_Right": "→", "Key_Backspace": "Backspace", "Key_Tab": "Tab",
             "Key_Delete": "Delete", "Key_Insert": "Insert", "Key_End": "End", "Key_Home": "Home",
             "Key_Slash": "/", "Key_Semicolon": ";", "Key_Apostrophe": "'", "Key_BracketLeft": "[",
             "Key_BracketRight": "]", "Key_Backslash": "\\", "Key_QuoteLeft": "`",
             "Key_MediaTogglePlayPause": "Media Play/Pause", "Key_VolumeUp": "Volume +", "Key_VolumeDown": "Volume −",
             "Key_VolumeMute": "Mute key"}
    return names.get(key_name, key_name.removeprefix("Key_"))


# --- Families and drawings -----------------------------------------------------------------------

def _b(control, label, x, y, shape="round", size=6.0, w=None, h=None, tint=""):
    return {"id": control, "label": label, "x": x, "y": y, "shape": shape,
            "w": w if w is not None else size, "h": h if h is not None else size, "tint": tint}


def _dpad(cx, cy, size=4.6, ids=("dpad_up", "dpad_down", "dpad_left", "dpad_right"), labels=("▲", "▼", "◀", "▶")):
    up, down, left, right = ids
    return [_b(up, labels[0], cx, cy - size, "dpad", size), _b(down, labels[1], cx, cy + size, "dpad", size),
            _b(left, labels[2], cx - size, cy, "dpad", size), _b(right, labels[3], cx + size, cy, "dpad", size)]


def _diamond(cx, cy, labels, spread=6.0, size=6.0, tints=("", "", "", "")):
    north, east, south, west = labels
    return [_b("north", north, cx, cy - spread, size=size, tint=tints[0]),
            _b("east", east, cx + spread, cy, size=size, tint=tints[1]),
            _b("south", south, cx, cy + spread, size=size, tint=tints[2]),
            _b("west", west, cx - spread, cy, size=size, tint=tints[3])]


def _shoulders(lb, rb, lt=None, rt=None, y=3.0):
    items = [_b("left_shoulder", lb, 22, y + 4, "bumper", w=16, h=4), _b("right_shoulder", rb, 78, y + 4, "bumper", w=16, h=4)]
    if lt:
        items.append(_b("left_trigger", lt, 22, y - 1, "trigger", w=11, h=5))
    if rt:
        items.append(_b("right_trigger", rt, 78, y - 1, "trigger", w=11, h=5))
    return items


def _stick(control, label, cx, cy, size=9.0):
    return _b(control, label, cx, cy, "stick", size)


def _modern(face, shoulders, view, menu, guide, misc="", *, ps_layout=False, touchpad=False):
    left_stick = (34, 42) if ps_layout else (25, 24)
    dpad = (24, 26) if ps_layout else (35, 40)
    view_at, menu_at = ((33, 13), (67, 13)) if ps_layout else ((40, 20), (60, 20))
    items = shoulders + face + _dpad(*dpad) + [
        _stick("left_stick", "L3", *left_stick), _stick("right_stick", "R3", 66, 42),
        _b("view", view, *view_at, "pill", w=7, h=3.6), _b("menu", menu, *menu_at, "pill", w=7, h=3.6)]
    if guide:
        items.append(_b("guide", guide, 50, 32 if ps_layout else 12, size=6.4))
    if misc:
        items.append(_b("misc", misc, 50, 39 if ps_layout else 27, "pill", w=6, h=2.8))
    if touchpad:
        items.append(_b("touchpad", "Touch", 50, 20, "pad", w=22, h=10))
    return items


def _deck():
    """Handheld layout: D-pad and face buttons up top, sticks below them."""
    return [_b("left_trigger", "L2", 14, 3.5, "trigger", w=11, h=5), _b("right_trigger", "R2", 86, 3.5, "trigger", w=11, h=5),
            _b("left_shoulder", "L1", 14, 9.5, "bumper", w=16, h=3.6), _b("right_shoulder", "R1", 86, 9.5, "bumper", w=16, h=3.6),
            *_dpad(13, 25, size=4.2), _stick("left_stick", "L3", 16, 42, size=8.5),
            *_diamond(87, 25, ("Y", "B", "A", "X"), spread=5, size=5),
            _stick("right_stick", "R3", 84, 42, size=8.5),
            _b("view", "View", 28, 14, "pill", w=6, h=3), _b("menu", "Menu", 72, 14, "pill", w=6, h=3),
            _b("guide", "Steam", 28, 50, "pill", w=8, h=3.4), _b("misc", "···", 72, 50, "pill", w=6, h=3),
            _b("paddle1", "L4", 6, 33, "pill", w=5, h=3), _b("paddle2", "L5", 6, 49, "pill", w=5, h=3),
            _b("paddle3", "R4", 94, 33, "pill", w=5, h=3), _b("paddle4", "R5", 94, 49, "pill", w=5, h=3)]


FAMILIES: tuple[dict[str, Any], ...] = (
    {"id": "xbox", "name": "Xbox", "detail": "Xbox 360, Xbox One and Xbox Series controllers", "body": "gamepad",
     "controls": _modern(_diamond(73, 26, ("Y", "B", "A", "X"), tints=("#f2c400", "#e43d30", "#45b649", "#1f8fe6")),
                         _shoulders("LB", "RB", "LT", "RT"), "View", "Menu", "Xbox", "Share")},
    {"id": "playstation", "name": "PlayStation", "detail": "DualShock and DualSense: PS1 through PS5", "body": "gamepad",
     "controls": _modern(_diamond(76, 26, ("△", "○", "✕", "□"), tints=("#3ec6a8", "#ef5a6f", "#7aa7ff", "#f08dd1")),
                         _shoulders("L1", "R1", "L2", "R2"), "Share", "Options", "PS", "Mute", ps_layout=True, touchpad=True)},
    {"id": "switch", "name": "Nintendo Switch", "detail": "Switch Pro Controller and Joy-Con pair", "body": "gamepad",
     "controls": _modern(_diamond(73, 26, ("X", "A", "B", "Y")), _shoulders("L", "R", "ZL", "ZR"), "−", "+", "Home", "Capture")},
    {"id": "gamecube", "name": "Nintendo GameCube", "detail": "GameCube controllers on a USB adapter", "body": "gamecube",
     "controls": [
         _b("left_trigger", "L", 22, 2.5, "trigger", w=14, h=5), _b("right_trigger", "R", 78, 2.5, "trigger", w=14, h=5),
         _b("right_shoulder", "Z", 78, 8, "bumper", w=12, h=3.4, tint="#8a5cf0"),
         _stick("left_stick", "Stick", 24, 24),
         _b("south", "A", 74, 25, size=10, tint="#2fb47c"), _b("west", "B", 65, 32, size=6, tint="#e2463b"),
         _b("east", "X", 83, 21, "bean", w=5, h=9), _b("north", "Y", 72, 15, "bean", w=9, h=5),
         _b("menu", "Start", 50, 24, size=4.6),
         *_dpad(35, 42, size=3.6),
         _b("rstick_up", "C▲", 64, 39, size=4.4, tint="#f2c400"), _b("rstick_down", "C▼", 64, 49, size=4.4, tint="#f2c400"),
         _b("rstick_left", "C◀", 59, 44, size=4.4, tint="#f2c400"), _b("rstick_right", "C▶", 69, 44, size=4.4, tint="#f2c400"),
     ]},
    {"id": "n64", "name": "Nintendo 64", "detail": "N64 controllers on a USB adapter or the Nintendo Switch Online pad", "body": "n64",
     "controls": [
         _b("left_shoulder", "L", 16, 6, "bumper", w=14, h=4), _b("right_shoulder", "R", 84, 6, "bumper", w=14, h=4),
         *_dpad(20, 22, size=4.2), _stick("left_stick", "Stick", 50, 32, size=8),
         _b("left_trigger", "Z", 50, 50, "trigger", w=9, h=5),
         _b("menu", "Start", 50, 18, size=5, tint="#e2463b"),
         _b("south", "A", 72, 28, size=7, tint="#2f6fe0"), _b("west", "B", 66, 21, size=7, tint="#2fb47c"),
         _b("rstick_up", "C▲", 82, 13, size=4.6, tint="#f2c400"), _b("rstick_down", "C▼", 82, 25, size=4.6, tint="#f2c400"),
         _b("rstick_left", "C◀", 76, 19, size=4.6, tint="#f2c400"), _b("rstick_right", "C▶", 88, 19, size=4.6, tint="#f2c400"),
     ]},
    {"id": "snes", "name": "Super Nintendo", "detail": "SNES and Super Famicom style pads", "body": "dogbone",
     "controls": [_b("left_shoulder", "L", 20, 9, "bumper", w=18, h=4), _b("right_shoulder", "R", 80, 9, "bumper", w=18, h=4),
                  *_dpad(24, 32, size=5), _b("view", "Select", 43, 34, "pill", w=8, h=3.4), _b("menu", "Start", 55, 34, "pill", w=8, h=3.4),
                  *_diamond(76, 32, ("X", "A", "B", "Y"), spread=6.5, size=7, tints=("#7f6bd6", "#d84a4a", "#e0b23c", "#3f9f5a"))]},
    {"id": "nes", "name": "Nintendo NES", "detail": "NES and Famicom style pads", "body": "brick",
     "controls": [*_dpad(22, 32, size=5), _b("view", "Select", 44, 36, "pill", w=8, h=3.4), _b("menu", "Start", 56, 36, "pill", w=8, h=3.4),
                  _b("south", "B", 71, 36, size=8, tint="#d84a4a"), _b("east", "A", 84, 36, size=8, tint="#d84a4a")]},
    {"id": "genesis", "name": "Sega Genesis / Mega Drive", "detail": "3- and 6-button pads", "body": "genesis",
     "controls": [*_dpad(24, 30, size=5.2), _b("menu", "Start", 50, 22, "pill", w=8, h=3.4), _b("view", "Mode", 50, 14, "pill", w=7, h=3),
                  _b("west", "A", 64, 36, size=6.6), _b("south", "B", 74, 34, size=6.6), _b("east", "C", 84, 32, size=6.6),
                  _b("left_shoulder", "X", 63, 26, size=5), _b("north", "Y", 72, 24, size=5), _b("right_shoulder", "Z", 81, 22, size=5)]},
    {"id": "dreamcast", "name": "Sega Dreamcast", "detail": "Dreamcast controllers on a USB adapter", "body": "gamepad",
     "controls": [_b("left_trigger", "L", 22, 3, "trigger", w=12, h=5), _b("right_trigger", "R", 78, 3, "trigger", w=12, h=5),
                  _stick("left_stick", "Stick", 26, 22), *_dpad(28, 40, size=4.4), _b("menu", "Start", 50, 38, size=4.6),
                  *_diamond(72, 30, ("Y", "B", "A", "X"), size=6, tints=("#f2c400", "#e2463b", "#2f6fe0", "#2fb47c"))]},
    {"id": "atari", "name": "Atari Joystick", "detail": "Classic one-button joysticks", "body": "stick",
     "controls": [_b("south", "Fire", 26, 18, size=9, tint="#e2463b"), *_dpad(55, 34, size=8, labels=("Up", "Down", "Left", "Right"))]},
    {"id": "steam", "name": "Steam Deck / Steam Controller", "detail": "Steam's built-in controls", "body": "deck",
     "controls": _deck()},
    {"id": "generic", "name": "Generic Gamepad", "detail": "Any other controller, by button position", "body": "gamepad",
     "controls": _modern(_diamond(73, 26, ("North", "East", "South", "West"), size=6.4), _shoulders("L1", "R1", "L2", "R2"),
                         "Back", "Start", "Guide")},
)
FAMILY_IDS = tuple(family["id"] for family in FAMILIES)
LAYOUT_CHOICES = ("auto",) + FAMILY_IDS


def detect_family(controller_type: str = "", name: str = "") -> str:
    """Pick the drawing for a connected controller from its SDL type and name."""
    text = f"{controller_type} {name}".lower()
    checks = (
        ("gamecube", ("gamecube", "game cube", "wii u gc", "mayflash gc")),
        ("n64", ("n64", "nintendo 64")),
        ("snes", ("snes", "super famicom", "super nintendo", "sn30")),
        ("nes", (" nes ", "nes controller", "famicom", "nes30", "n30")),
        ("genesis", ("genesis", "mega drive", "megadrive", "m30", "sega 6")),
        ("dreamcast", ("dreamcast",)),
        ("atari", ("atari", "2600", "cx40")),
        ("steam", ("steam deck", "steam controller", "valve")),
        ("playstation", ("ps3", "ps4", "ps5", "playstation", "dualshock", "dualsense", "sony")),
        ("switch", ("switch", "joy-con", "joycon", "pro controller", "nintendo")),
        ("xbox", ("xbox", "xinput", "x-box", "microsoft")),
    )
    padded = f" {text} "
    for family, words in checks:
        if any(word in padded for word in words):
            return family
    return "generic"


def family_by_id(family_id: str) -> dict[str, Any]:
    return next((family for family in FAMILIES if family["id"] == family_id), FAMILIES[-1])
