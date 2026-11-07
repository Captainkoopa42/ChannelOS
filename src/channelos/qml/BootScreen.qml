import QtQuick

// The boot / loading screen: optional TV static behind one of three loading
// styles. Used by the startup window, by Main while the first channel loads,
// and by the Settings preview. `progress` is real startup progress (0..1).
Item {
    id: boot
    objectName: "bootScreen"

    property string loadingStyle: "tv"   // classic | bar | tv (dancing TV is the default)
    property bool showStatic: true
    property bool reducedMotion: false
    property real progress: 0
    property string message: "Tuning in…"
    property bool running: visible
    readonly property string effectiveStyle: reducedMotion && loadingStyle === "tv" ? "bar" : loadingStyle
    readonly property real shownProgress: Math.max(0, Math.min(1, progress))
    readonly property url mascotBase: Qt.resolvedUrl("../assets/mascot/")

    Rectangle {
        anchors.fill: parent
        color: Theme.c("#050c15")
    }

    // TV static, like an empty channel.
    Item {
        id: noise
        anchors.fill: parent
        visible: boot.showStatic
        clip: true
        property int frame: 0
        // Four pre-made frames (assets/static), flipped and nudged: no
        // per-pixel drawing, so the first frame appears immediately.
        Repeater {
            model: 4
            delegate: Image {
                required property int index
                source: Qt.resolvedUrl("../assets/static/noise" + index + ".png")
                width: 320
                height: 180
                scale: Math.max(noise.width / width, noise.height / height) * 1.1
                transformOrigin: Item.TopLeft
                x: noise.frame % 2 === 0 ? 0 : -noise.width * 0.04
                y: noise.frame % 3 === 0 ? 0 : -noise.height * 0.04
                smooth: false
                mipmap: false
                visible: noise.frame % 4 === index
            }
        }
        Timer {
            interval: boot.reducedMotion ? 400 : 70
            repeat: true
            running: boot.running && boot.showStatic
            onTriggered: noise.frame = (noise.frame + 1 + Math.floor(Math.random() * 3)) % 12
        }
    }
    Rectangle {
        // Darken the static so the loading style reads clearly on top.
        anchors.fill: parent
        visible: boot.showStatic
        color: Theme.v("#000000")
        opacity: 0.45
    }

    // Classic: wordmark, message and a slim progress line.
    Column {
        objectName: "bootClassic"
        anchors.centerIn: parent
        width: Math.min(parent.width - 80, 620)
        spacing: 18
        visible: boot.effectiveStyle === "classic"
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 2
            Text { text: "Channel"; color: Theme.v("#f4f7fb"); font.pixelSize: 54; font.weight: Font.DemiBold }
            Text { text: "OS"; color: Theme.c("#42adff"); font.pixelSize: 54; font.weight: Font.DemiBold }
        }
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.width * 0.6
            height: 4
            radius: 2
            color: Theme.v("#1a3550")
            Rectangle {
                width: parent.width * boot.shownProgress
                height: parent.height
                radius: 2
                color: Theme.c("#42adff")
                Behavior on width { enabled: !boot.reducedMotion; NumberAnimation { duration: 260 } }
            }
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: boot.message
            color: Theme.v("#c8d4e2")
            font.pixelSize: 18
            style: Text.Outline
            styleColor: Theme.v("#000000")
            wrapMode: Text.Wrap
        }
    }

    // Fill bar: a full-width bar along the bottom edge.
    Item {
        objectName: "bootBar"
        anchors.fill: parent
        visible: boot.effectiveStyle === "bar"
        Text {
            anchors.left: parent.left
            anchors.bottom: barTrack.top
            anchors.leftMargin: 32
            anchors.bottomMargin: 14
            text: boot.message
            color: Theme.v("#c8d4e2")
            font.pixelSize: 16
            style: Text.Outline
            styleColor: Theme.v("#000000")
        }
        Text {
            anchors.right: parent.right
            anchors.bottom: barTrack.top
            anchors.rightMargin: 32
            anchors.bottomMargin: 14
            text: Math.round(boot.shownProgress * 100) + "%"
            color: Theme.c("#42adff")
            font.pixelSize: 16
            font.weight: Font.DemiBold
        }
        Rectangle {
            id: barTrack
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 10
            color: Theme.v("#0d2035")
            Rectangle {
                width: parent.width * boot.shownProgress
                height: parent.height
                color: Theme.c("#1a91ff")
                Behavior on width { enabled: !boot.reducedMotion; NumberAnimation { duration: 300 } }
                Rectangle {
                    anchors.right: parent.right
                    width: Math.min(parent.width, 80)
                    height: parent.height
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0; color: "transparent" }
                        GradientStop { position: 1; color: Theme.c("#42adff") }
                    }
                }
            }
        }
    }

    // Dancing TV: the app's mascot hops to a beat, antennas springing, and
    // the guide rows on its screen light up as startup progresses.
    Item {
        id: dance
        objectName: "bootTv"
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -20
        visible: boot.effectiveStyle === "tv"
        readonly property real size: Math.min(boot.width, boot.height) * 0.42
        readonly property real unit: size / 512
        width: size
        height: size + 80

        property real beat: 0          // 0..1 within each hop
        property int beats: 0
        SequentialAnimation {
            loops: Animation.Infinite
            running: dance.visible && boot.running
            NumberAnimation { target: dance; property: "beat"; from: 0; to: 1; duration: 620 }
            ScriptAction { script: dance.beats += 1 }
        }
        readonly property real hop: Math.sin(beat * Math.PI)                       // 0..1..0
        readonly property real landing: Math.max(0, 1 - beat / 0.18)               // squash after landing
        readonly property real swayTarget: (beats % 2 === 0 ? 1 : -1)

        // Shadow shrinks as the TV rises.
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            y: dance.size * 0.955
            width: dance.size * (0.62 - 0.18 * dance.hop)
            height: dance.size * 0.05
            radius: height / 2
            color: Theme.v("#000000")
            opacity: 0.38 - 0.16 * dance.hop
        }

        Item {
            id: tv
            width: dance.size
            height: dance.size
            x: dance.swayTarget * dance.size * 0.035 * Math.sin(dance.beat * Math.PI)
            y: -dance.size * 0.16 * dance.hop
            rotation: dance.swayTarget * 5 * Math.sin(dance.beat * Math.PI)
            transformOrigin: Item.Bottom
            transform: Scale {
                origin.x: tv.width / 2
                origin.y: tv.height * 0.95
                xScale: 1 + 0.08 * dance.landing - 0.03 * dance.hop
                yScale: 1 - 0.1 * dance.landing + 0.05 * dance.hop
            }

            // Antennas spring behind the hop (they lag the body).
            Image {
                source: boot.mascotBase + "antenna_left.png"
                anchors.fill: parent
                smooth: true
                mipmap: true
                transform: Rotation {
                    origin.x: 240 * dance.unit
                    origin.y: 110 * dance.unit
                    angle: -14 * Math.sin((dance.beat - 0.18) * Math.PI * 2)
                }
            }
            Image {
                source: boot.mascotBase + "antenna_right.png"
                anchors.fill: parent
                smooth: true
                mipmap: true
                transform: Rotation {
                    origin.x: 272 * dance.unit
                    origin.y: 110 * dance.unit
                    angle: 14 * Math.sin((dance.beat - 0.3) * Math.PI * 2)
                }
            }
            Image {
                source: boot.mascotBase + "body.png"
                anchors.fill: parent
                smooth: true
                mipmap: true
            }
            // Screen rows: dim until progress reaches them, then light up.
            Repeater {
                model: [[205, 238], [254, 287], [303, 337]]
                delegate: Rectangle {
                    required property var modelData
                    required property int index
                    readonly property real lit: Math.max(0, Math.min(1, boot.shownProgress * 3 - index))
                    x: 128 * dance.unit
                    y: modelData[0] * dance.unit
                    width: (388 - 128) * dance.unit
                    height: (modelData[1] - modelData[0] + 1) * dance.unit
                    radius: 3 * dance.unit
                    color: Theme.v("#061633")
                    opacity: 0.78 * (1 - lit)
                    Behavior on opacity { NumberAnimation { duration: 240 } }
                }
            }
            // Power light blinks to the beat.
            Rectangle {
                x: 104 * dance.unit
                y: 421 * dance.unit
                width: 28 * dance.unit
                height: 12 * dance.unit
                radius: 4 * dance.unit
                color: Theme.v("#0a2a0a")
                opacity: dance.beats % 2 === 0 ? 0 : 0.75
            }
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: dance.size + 28
            text: boot.message
            color: Theme.v("#e6edf5")
            font.pixelSize: 18
            style: Text.Outline
            styleColor: Theme.v("#000000")
            font.weight: Font.DemiBold
        }
    }
}
