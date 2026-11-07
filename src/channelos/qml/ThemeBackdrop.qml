import QtQuick

// The background of a full screen: the theme colour, plus the theme's
// wallpaper when it has one. Panels above may be translucent.
Item {
    id: backdrop
    Rectangle {
        anchors.fill: parent
        color: Theme.base
    }
    Image {
        anchors.fill: parent
        visible: Theme.wallpaper !== "" && status === Image.Ready
        source: Theme.wallpaper
        asynchronous: true
        cache: true
        smooth: true
        opacity: Theme.wallpaperOpacity
        fillMode: Theme.wallpaperFit === "fit" ? Image.PreserveAspectFit
                  : Theme.wallpaperFit === "tile" ? Image.Tile
                  : Theme.wallpaperFit === "center" ? Image.Pad
                  : Image.PreserveAspectCrop
        horizontalAlignment: Image.AlignHCenter
        verticalAlignment: Image.AlignVCenter
        // Decode near screen size; a 6000px photo should not cost 100 MB.
        sourceSize.width: Theme.wallpaperFit === "tile" || Theme.wallpaperFit === "center" ? 0 : Math.max(1, width)
    }
}
