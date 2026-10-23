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
                text: "RECONSTRUCTION / MASTERING"
                font.family: "Oxanium"
                font.pixelSize: 18
                color: "#5fe7ef"
            }

            Item { Layout.fillWidth: true }

            Label {
                text: "Target: -14 LUFS / -1 dBTP"
                font.family: "JetBrains Mono"
                color: "#7f929b"
            }
        }

        ListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 8
            model: bci.recordings

            delegate: Rectangle {
                required property var modelData
                width: ListView.view.width
                height: 116
                radius: 10
                color: "#091016"
                border.color: "#24343d"

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 10

                    ColumnLayout {
                        Layout.fillWidth: true

                        Label {
                            text: modelData.key
                            font.family: "Oxanium"
                            color: "#e8eff1"
                        }

                        Label {
                            text: String(modelData.master).length > 0 ? "MASTER AVAILABLE" : "MASTER NOT RENDERED"
                            font.family: "JetBrains Mono"
                            color: String(modelData.master).length > 0 ? "#78e5c5" : "#82939b"
                        }

                        Label {
                            Layout.fillWidth: true
                            text: String(modelData.isolated).length > 0 ? modelData.isolated : modelData.raw
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9
                            color: "#657981"
                            elide: Text.ElideMiddle
                        }
                    }

                    Button {
                        text: "RECONSTRUCT"
                        enabled: String(modelData.raw).length > 0 && String(modelData.isolated).length > 0
                        onClicked: bci.reconstruct(modelData.raw, modelData.isolated)
                    }

                    Button {
                        text: "MASTER"
                        enabled: String(modelData.isolated).length > 0
                        onClicked: bci.master(modelData.isolated)
                    }

                    Button {
                        text: "PLAY BEST"
                        onClicked: bci.playRecording(
                            String(modelData.master).length > 0
                                ? modelData.master
                                : modelData.preferred
                        )
                    }
                }
            }
        }
    }
}
