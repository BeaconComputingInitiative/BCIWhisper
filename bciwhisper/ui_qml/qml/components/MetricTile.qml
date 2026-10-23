import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    property string label: ""
    property string value: ""
    property string detail: ""

    implicitHeight: 104
    radius: 15
    color: "#0b1a29"
    border.color: "#2d6170"

    Rectangle {
        anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
        anchors.leftMargin: 17; anchors.rightMargin: 17
        height: 2; color: "#51c8d9"; opacity: .75
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 3

        Label {
            text: root.label
            font.family: "Rajdhani"
            font.pixelSize: 12
            color: "#718690"
        }

        Label {
            text: root.value
            font.family: "Oxanium"
            font.pixelSize: 24
            font.weight: Font.DemiBold
            color: "#e8fbff"
        }

        Label {
            visible: root.detail.length > 0
            text: root.detail
            font.family: "JetBrains Mono"
            font.pixelSize: 9
            color: "#67808a"
            elide: Text.ElideRight
            Layout.fillWidth: true
        }
    }
}
