// BEACON COMPUTING INITIATIVE
// BCIWhisper Script 59.0 | Podcast Lab Studio Baseline
// Developer Seal: CJB-DEV-2026

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"
import "pages"

ApplicationWindow {
    id: window
    visible: true
    width: 1440
    height: 920
    minimumWidth: 1040
    minimumHeight: 680
    title: "BCIWhisper Podcast Lab // " + bci.projectVersion + " // Script " + bci.scriptRevision
    color: "#05080d"

    palette.window: "#05080d"
    palette.windowText: "#dce6ec"
    palette.base: "#0b0f14"
    palette.text: "#dce6ec"
    palette.button: "#111820"
    palette.buttonText: "#dce6ec"
    palette.highlight: "#164652"
    palette.highlightedText: "#ffffff"

    property int pageIndex: 0

    header: Rectangle {
        height: 88
        color: "#080b10"
        border.color: "#421923"
        border.width: 1

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 22
            anchors.rightMargin: 22
            spacing: 18

            ColumnLayout {
                spacing: 0

                Label {
                    text: "BEACON COMPUTING INITIATIVE"
                    font.family: "Oxanium"
                    font.pixelSize: 12
                    color: "#5fe7ef"
                }

                Label {
                    text: "BCIWhisper PODCAST LAB"
                    font.family: "Oxanium"
                    font.pixelSize: 29
                    font.weight: Font.Bold
                    color: "#f2f6f7"
                }
            }

            Item { Layout.fillWidth: true }

            ColumnLayout {
                Layout.alignment: Qt.AlignVCenter
                spacing: 2

                Label {
                    text: bci.deviceName.length > 0 ? bci.deviceName : "Awaiting capture"
                    font.family: "Rajdhani"
                    font.pixelSize: 14
                    color: "#d5e0e4"
                }

                Label {
                    text: bci.phase.toUpperCase() + " • " +
                          (bci.sampleRate > 0 ? bci.sampleRate + " Hz" : "no stream") +
                          " • PID " + bci.audioProcessPid
                    font.family: "JetBrains Mono"
                    font.pixelSize: 10
                    color: "#768a93"
                }
            }

            Rectangle {
                implicitWidth: liveLabel.implicitWidth + 24
                implicitHeight: 30
                radius: 15
                color: bci.goLive ? "#11372e" : (bci.signalActive ? "#18313a" : "#171d22")
                border.color: bci.goLive ? "#4ebc96" : "#31414a"

                Label {
                    id: liveLabel
                    anchors.centerIn: parent
                    text: bci.goLive ? "LIVE" : (bci.signalActive ? "SIGNAL" : "MONITORING")
                    font.family: "JetBrains Mono"
                    font.pixelSize: 10
                    font.weight: Font.Bold
                    color: bci.goLive ? "#7cf0c8" : "#9eb1b8"
                }
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 12

        Rectangle {
            Layout.preferredWidth: 188
            Layout.fillHeight: true
            radius: 12
            color: "#080d12"
            border.color: "#202e35"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 6

                Repeater {
                    model: [
                        "STUDIO",
                        "MONITOR",
                        "RECORDINGS",
                        "TRANSCRIPTS",
                        "MASTERING",
                        "GO LIVE",
                        "TELEMETRY",
                        "SETTINGS"
                    ]

                    delegate: Button {
                        required property string modelData
                        required property int index
                        Layout.fillWidth: true
                        text: modelData
                        checkable: true
                        checked: window.pageIndex === index
                        onClicked: window.pageIndex = index
                    }
                }

                Item { Layout.fillHeight: true }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: statusColumn.implicitHeight + 18
                    radius: 8
                    color: "#0c1319"
                    border.color: "#21323b"

                    ColumnLayout {
                        id: statusColumn
                        anchors.fill: parent
                        anchors.margins: 9
                        spacing: 4

                        Label {
                            text: "NATIVE"
                            font.family: "Rajdhani"
                            color: "#71838b"
                        }

                        Label {
                            text: bci.nativeLoaded ? "C++20 ACTIVE" : "NUMPY FALLBACK"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9
                            color: bci.nativeLoaded ? "#78e5c5" : "#ffd58b"
                        }

                        Label {
                            text: bci.nativeSelfTest
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9
                            color: bci.nativeSelfTest === "PASS" ? "#78e5c5" : "#ff858e"
                        }
                    }
                }

                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    visible: bci.lastError.length > 0
                    text: bci.lastError
                    font.family: "JetBrains Mono"
                    font.pixelSize: 9
                    color: "#ff858e"
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 12
            color: "#070b10"
            border.color: "#202e35"

            StackLayout {
                anchors.fill: parent
                anchors.margins: 14
                currentIndex: window.pageIndex

                StudioPage {}
                MonitorPage {}
                RecordingsPage {}
                TranscriptPage {}
                MasteringPage {}
                LivePage {}
                TelemetryPage {}
                SettingsPage {}
            }
        }
    }

    footer: Rectangle {
        height: 34
        color: "#070b10"
        border.color: "#421923"

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 14

            Label {
                text: bci.projectVersion + " • Script " + bci.scriptRevision + " • " + bci.engineeringBuild
                font.family: "JetBrains Mono"
                font.pixelSize: 9
                color: "#6f8189"
            }

            Item { Layout.fillWidth: true }

            Label {
                text: "Observe accurately • Preserve faithfully • Analyze transparently • Communicate securely • Act deliberately"
                font.family: "Rajdhani"
                color: "#6f8189"
            }
        }
    }
}
