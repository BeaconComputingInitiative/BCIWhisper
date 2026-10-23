import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    ColumnLayout {
        anchors.fill: parent
        spacing: 14

        Label {
            text: "BCI LIVE BROADCAST"
            font.family: "Oxanium"
            font.pixelSize: 20
            color: "#5fe7ef"
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 160
            radius: 12
            color: "#090f15"
            border.color: bci.goLive ? "#2c7b67" : "#273640"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18
                spacing: 10

                RowLayout {
                    Layout.fillWidth: true

                    Label {
                        text: bci.goLive ? "LIVE" : "OFFLINE"
                        font.family: "Oxanium"
                        font.pixelSize: 28
                        color: bci.goLive ? "#78e5c5" : "#84939b"
                    }

                    Item { Layout.fillWidth: true }

                    Button {
                        text: bci.goLive ? "STOP LIVE" : "GO LIVE"
                        onClicked: bci.setGoLive(!bci.goLive)
                    }
                }

                Label {
                    Layout.fillWidth: true
                    text: bci.goLive ? bci.playerUrl : "The local gateway is started only while Go Live is active."
                    font.family: "JetBrains Mono"
                    color: "#9babb2"
                    elide: Text.ElideMiddle
                }

                Label {
                    text: bci.sampleRate > 0 ? "PCM16 publisher • " + bci.sampleRate + " Hz mono → MP3 gateway" : "Waiting for live capture"
                    font.family: "Rajdhani"
                    color: "#72868f"
                }
            }
        }

        Item { Layout.fillHeight: true }
    }
}
