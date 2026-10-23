import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// BEACON COMPUTING INITIATIVE
// BCIWhisper Render Control Panel
// Developer Seal: CJB-DEV-2026
// Source integrity: SHA-256 established during packaged build
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
                    text: bci.goLive ? bci.playerUrl : "Render Cloud • publisher disconnected"
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

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: remoteControls.implicitHeight + 36
            radius: 12
            color: "#090f15"
            border.color: "#273640"

            ColumnLayout {
                id: remoteControls
                anchors.fill: parent
                anchors.margins: 18
                spacing: 10

                Label {
                    text: "RENDER CLOUD GATEWAY"
                    font.family: "Oxanium"
                    font.pixelSize: 17
                    color: "#5fe7ef"
                }

                Label {
                    text: "https://bciwhisper-live.onrender.com"
                    color: "#c6d7de"
                    font.family: "JetBrains Mono"
                    Layout.fillWidth: true
                    elide: Text.ElideMiddle
                }

                Label {
                    text: bci.publisherConfigured ? "Publisher credential: CONFIGURED" : "Publisher credential: REQUIRED"
                    color: bci.publisherConfigured ? "#78e5c5" : "#ffd58b"
                    font.family: "Rajdhani"
                }

                RowLayout {
                    Layout.fillWidth: true
                    TextField {
                        id: publisherField
                        Layout.fillWidth: true
                        placeholderText: "Paste Render publisher token once"
                        echoMode: TextInput.Password
                        enabled: !bci.goLive
                        selectByMouse: true
                    }
                    Button {
                        text: "SAVE TOKEN"
                        enabled: publisherField.text.length > 0 && !bci.goLive
                        onClicked: {
                            bci.savePublisherToken(publisherField.text)
                            publisherField.text = ""
                        }
                    }
                }

                Label {
                    text: "Stored privately on this computer (0600). Never included in the repository."
                    color: "#71838b"
                    font.family: "Rajdhani"
                }

                Button {
                    text: "OPEN STREAMPLAYER"
                    onClicked: Qt.openUrlExternally(bci.renderPlayerUrl)
                }
            }
        }

        Item { Layout.fillHeight: true }
    }
}
