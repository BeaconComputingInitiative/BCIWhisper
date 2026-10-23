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
                text: "RECORDINGS LIBRARY"
                font.family: "Oxanium"
                font.pixelSize: 18
                color: "#5fe7ef"
            }

            Item { Layout.fillWidth: true }

            Button {
                text: "REFRESH"
                onClicked: bci.refreshRecordings()
            }

            Button {
                text: "STOP PLAYBACK"
                onClicked: bci.stopPlayback()
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
                height: 112
                radius: 10
                color: "#0a1016"
                border.color: "#22333d"

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 10

                    ColumnLayout {
                        Layout.fillWidth: true

                        Label {
                            text: modelData.key
                            font.family: "Oxanium"
                            color: "#e5edef"
                            font.pixelSize: 15
                        }

                        Label {
                            text: Number(modelData.duration).toFixed(1) + " s"
                            font.family: "JetBrains Mono"
                            color: "#83959d"
                        }

                        Label {
                            Layout.fillWidth: true
                            text: modelData.preferred
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9
                            color: "#647982"
                            elide: Text.ElideMiddle
                        }
                    }

                    Button {
                        text: "PLAY"
                        onClicked: bci.playRecording(modelData.preferred)
                    }

                    Button {
                        text: "REBUILD"
                        enabled: String(modelData.raw).length > 0 && String(modelData.isolated).length > 0
                        onClicked: bci.reconstruct(modelData.raw, modelData.isolated)
                    }

                    Button {
                        text: "MASTER"
                        enabled: String(modelData.isolated).length > 0
                        onClicked: bci.master(modelData.isolated)
                    }

                    Button {
                        text: "TRANSCRIBE"
                        onClicked: bci.transcribe(modelData.preferred)
                    }
                }
            }
        }
    }
}
