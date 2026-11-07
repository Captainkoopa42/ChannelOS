pragma Singleton
import QtQuick

// One place for the look of ChannelOS. Every screen writes its colours as
// Theme.c("#original"): the ChannelOS theme returns them unchanged, other
// themes map each one to their own palette. Bindings re-evaluate when
// `name` changes, so switching themes is live.
QtObject {
    id: theme

    property string name: "channelos"
    readonly property var names: ["channelos", "chromespace"]
    // A Theme Builder theme (or live preview): its full colour map and
    // wallpaper, computed in Python from the theme's role colours.
    property var spec: ({})
    readonly property var custom: spec && spec.palette && spec.name === name
                                  && String(name).indexOf("custom-") === 0 ? spec.palette : null
    readonly property string wallpaper: custom && spec.wallpaper ? String(spec.wallpaper) : ""
    readonly property string wallpaperFit: spec && spec.wallpaperFit ? String(spec.wallpaperFit) : "fill"
    readonly property real wallpaperOpacity: spec && spec.wallpaperOpacity ? Number(spec.wallpaperOpacity) / 100 : 1
    // Background behind every screen; always opaque (the wallpaper sits on it).
    readonly property color base: Qt.rgba(Qt.color(c("#050c15")).r, Qt.color(c("#050c15")).g,
                                          Qt.color(c("#050c15")).b, 1)
    readonly property bool light: Qt.color(c("#081625")).hslLightness > 0.5

    // ChromeSpace: Chrome's light surfaces and tab-strip grey with MySpace's
    // navy blue and orange highlights. Generated from the ChannelOS palette
    // by role (surface, selection, accent, text), then hand-tuned anchors.
    readonly property var palettes: ({
        "chromespace": {
            "#020913": "#e0e5eb",
            "#05000000": "#05000000",
            "#050a11": "#e0e5eb",
            "#050c15": "#e8ebf0",
            "#050d18": "#e2e6ec",
            "#06101a": "#e3e7ed",
            "#06101d": "#e3e8ed",
            "#06111e": "#e4e8ee",
            "#07111c": "#e3e8ed",
            "#07111e": "#e4e8ee",
            "#07131f": "#e4e8ee",
            "#071321": "#e5e9ee",
            "#071322": "#e5e9ee",
            "#071421": "#e5e9ee",
            "#071728": "#e6eaef",
            "#071827": "#e6eaef",
            "#08131f": "#e4e8ee",
            "#081522": "#e5e9ee",
            "#081625": "#ffffff",
            "#081712": "#e0f5ee",
            "#091522": "#e5e9ef",
            "#091827": "#e6eaef",
            "#0a1022": "#e6e9ef",
            "#0a1522": "#e6e9ef",
            "#0a1826": "#e6eaef",
            "#0a1a29": "#e7ebf0",
            "#0a1a2b": "#e8ebf0",
            "#0a1b2d": "#e8ecf0",
            "#0a1c32": "#e9edf1",
            "#0a66ad": "#194590",
            "#0b1622": "#e6eaef",
            "#0b1b2b": "#e8ebf0",
            "#0b1b2e": "#e9ecf1",
            "#0b2031": "#e9edf1",
            "#0b2034": "#c6d9f2",
            "#0b2136": "#c6d9f2",
            "#0d1b28": "#e8ebf0",
            "#0d2035": "#f5f7fa",
            "#0d2134": "#c6d9f2",
            "#0d2744": "#c9dbf2",
            "#0d2b4b": "#cbdcf3",
            "#0e2842": "#c9dbf2",
            "#10151b": "#e5e9ef",
            "#10283f": "#e3edf9",
            "#102a43": "#cadbf2",
            "#102b50": "#ccddf3",
            "#102d49": "#cbdcf3",
            "#103568": "#d1e0f4",
            "#111820": "#e7eaef",
            "#111f2c": "#e9edf1",
            "#12304a": "#cbddf3",
            "#12304d": "#ccddf3",
            "#123558": "#cedef4",
            "#123628": "#e0f5ed",
            "#12396a": "#d2e1f4",
            "#123b60": "#d0dff4",
            "#12527f": "#d6e4f5",
            "#142634": "#eceff3",
            "#14283b": "#eef0f4",
            "#142b40": "#cadbf3",
            "#14304a": "#ccddf3",
            "#143a5c": "#cfdff4",
            "#14558a": "#d9e5f6",
            "#146ad1": "#fde2cc",
            "#153b60": "#d0e0f4",
            "#160b19": "#e4e8ee",
            "#162a3a": "#eef0f4",
            "#163b5d": "#d0e0f4",
            "#164d80": "#d7e4f6",
            "#171108": "#fcf0de",
            "#17202a": "#eaeef2",
            "#172e40": "#f0f2f5",
            "#17324a": "#ccddf3",
            "#173452": "#cedef4",
            "#173653": "#cedef4",
            "#174e36": "#e0f5ec",
            "#176aa6": "#1a4591",
            "#18000000": "#18000000",
            "#193a55": "#cfdff4",
            "#1a3550": "#c5d0de",
            "#1a3b52": "#cfdff4",
            "#1a4d82": "#d8e5f6",
            "#1a91ff": "#1d4fa8",
            "#1c3348": "#f3f4f7",
            "#21151c": "#e8ebf0",
            "#243d55": "#f8f9fa",
            "#244238": "#f3f5f7",
            "#24577d": "#d9e6f6",
            "#27445e": "#fafbfc",
            "#293a63": "#fcfcfd",
            "#294158": "#f9fafb",
            "#2a1014": "#fcdee3",
            "#2bcf75": "#1e8e3e",
            "#31465b": "#fcfcfd",
            "#32151b": "#fcdee4",
            "#35131a": "#fcdee4",
            "#351b24": "#eef0f4",
            "#3a1518": "#fcdee0",
            "#3a2e17": "#fcf2de",
            "#401c25": "#fcdee6",
            "#42adff": "#ec6a12",
            "#463719": "#fcf2de",
            "#4a314d": "#f9fafb",
            "#4b3717": "#fcf1de",
            "#4b3d25": "#f5f7f9",
            "#54212a": "#fcdee3",
            "#55687c": "#8999b8",
            "#607489": "#7c8db0",
            "#6b5326": "#fcf2de",
            "#70869c": "#687ca5",
            "#71869c": "#687ca4",
            "#7a1d1d": "#fcdede",
            "#7f93a8": "#5c7099",
            "#8a02070d": "#8adfe4ea",
            "#8fa9c2": "#4e5f81",
            "#91b9e1": "#f0690f",
            "#9a050a11": "#9ae0e5eb",
            "#9a6a20": "#d15e05",
            "#9fb0c2": "#5b6678",
            "#a3b6ca": "#445371",
            "#a83232": "#d41111",
            "#aa02070d": "#aadfe4ea",
            "#b0050c15": "#b0e8ebf0",
            "#b7c5d5": "#3a4660",
            "#b8050c15": "#b8e8ebf0",
            "#b8081625": "#b8ffffff",
            "#b8c7d6": "#39465f",
            "#b95769": "#d41135",
            "#bb02070d": "#bbdfe4ea",
            "#c5ccd4": "#354159",
            "#c8050a11": "#c8e0e5eb",
            "#c9060c14": "#c9e1e6ec",
            "#cc02070d": "#ccdfe4ea",
            "#d9142b46": "#d9cbdcf3",
            "#d99b36": "#d15e05",
            "#d9ecff": "#f0690f",
            "#dc081625": "#dcffffff",
            "#e6081625": "#e6ffffff",
            "#ed050c15": "#ede8ebf0",
            "#f0f6ff": "#f0690f",
            "#f20a1725": "#f2e6eaef",
            "#f4071422": "#f4e5e9ee",
            "#f4f7fb": "#1b2540",
            "#ff4a4a": "#d93025",
            "#ff6666": "#c5221f",
            "#ff8585": "#d41111",
            "#ffb84a": "#c26401",
            "#ffd8df": "#d41134",
            "#ffffff": "#ffffff",
            // Text on checked or focused (not primary) controls: white on the
            // dark theme, ink on ChromeSpace's light selection tint.
            "#fffffe": "#1b2540"
        }
    })

    // Colours drawn over video (HUDs, previews, static) keep the dark
    // broadcast look in every theme so they stay readable on any picture.
    function v(hex) {
        return hex
    }

    function c(hex) {
        var palette = custom || palettes[name]
        if (!palette)
            return hex
        var mapped = palette[String(hex).toLowerCase()]
        return mapped === undefined ? hex : mapped
    }
}
