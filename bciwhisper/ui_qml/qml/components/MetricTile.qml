import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    property string label: ""
    property string value: ""
    property string detail: ""

    implicitHeight: 82
    radius: 10
    color: "#0a1016"
    border.color: "#22333d"

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
            font.pixelSize: 22
            font.weight: Font.DemiBold
            color: "#ecf4f6"
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
