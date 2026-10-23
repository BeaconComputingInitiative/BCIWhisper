import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    ColumnLayout {
        anchors.fill: parent
        spacing: 10

        RowLayout {
            Layout.fillWidth: true

            Label {
                text: "TELEMETRY / EVENTS"
                font.family: "Oxanium"
                font.pixelSize: 18
                color: "#5fe7ef"
            }

            Item { Layout.fillWidth: true }

            Button {
                text: "REFRESH"
                onClicked: bci.refreshTelemetry()
            }
        }

        ListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 4
            model: bci.telemetryEvents

            delegate: Rectangle {
                required property var modelData
                width: ListView.view.width
                height: 62
                color: "#090f14"
                border.color: "#1e2b32"
                radius: 6

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 9

                    Label {
                        text: modelData.name
                        font.family: "JetBrains Mono"
                        color: "#dce7ea"
                        Layout.preferredWidth: 210
                    }

                    Label {
                        Layout.fillWidth: true
                        text: JSON.stringify(modelData.payload)
                        font.family: "JetBrains Mono"
                        font.pixelSize: 9
                        color: "#71838b"
                        elide: Text.ElideRight
                    }
                }
            }
        }
    }
}
