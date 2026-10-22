// BEACON COMPUTING INITIATIVE
// BCIWhisper Script 58.2 | Engineering Build 2026.10.22-r6.35.2
// Developer Seal: CJB-DEV-2026
// Canonical Payload SHA-256: aaffad69eee40fa7c7e04e4db0924e9a48b0b98bb2438d45922a36aa432e40ef
// Integrity rule: hash covers this file's payload below this header, if and only if the payload is unchanged.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "components"

ApplicationWindow {
    id: window
    visible: true
    width: 1380
    height: 900
    minimumWidth: 900
    minimumHeight: 620
    title: "BCIWhisper // " + bci.projectVersion + " // Script " + bci.scriptRevision

    color: "#05080d"

    palette.window: "#05080d"
    palette.windowText: "#dce6ec"
    palette.base: "#0b0f14"
    palette.text: "#dce6ec"
    palette.button: "#111820"
    palette.buttonText: "#dce6ec"
    palette.highlight: "#164652"
    palette.highlightedText: "#ffffff"

    header: Rectangle {
        height: 92
        color: "#080b10"
        border.color: "#471722"
        border.width: 1

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 24
            anchors.rightMargin: 24
            spacing: 18

            ColumnLayout {
                spacing: 1

                Label {
                    text: "BEACON COMPUTING INITIATIVE"
                    font.family: "Oxanium"
                    font.pixelSize: 13
                    color: "#5fe7ef"
                }

                Label {
                    text: "BCIWhisper"
                    font.family: "Oxanium"
                    font.pixelSize: 30
                    font.weight: Font.Bold
                    color: "#f3f6f7"
                }
            }

            Item { Layout.fillWidth: true }

            ColumnLayout {
                spacing: 2

                Label {
                    text: bci.projectVersion + " / Script " + bci.scriptRevision
                    font.family: "JetBrains Mono"
                    color: "#dce6ec"
                }

                Label {
                    text: bci.engineeringBuild
                    font.family: "JetBrains Mono"
                    color: "#85939c"
                }
            }
        }
    }

    FileDialog {
        id: audioPicker
        title: "Select audio for local transcription"
        nameFilters: ["Audio files (*.wav *.mp3 *.m4a *.flac *.ogg)", "All files (*)"]
        onAccepted: bci.transcribeFile(selectedFile.toString())
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 18
        spacing: 12

        TabBar {
            id: tabs
            Layout.fillWidth: true

            Repeater {
                model: ["MONITOR", "RECORDINGS", "TRANSCRIPTS", "MASTERING"]

                TabButton {
                    required property string modelData
                    text: modelData
                    font.family: "Oxanium"
                }
            }
        }

        StackLayout {
            currentIndex: tabs.currentIndex
            Layout.fillWidth: true
            Layout.fillHeight: true

            ScrollView {
                clip: true

                ColumnLayout {
                    width: parent.width
                    spacing: 12

                    ArchitectureCard {}

                    PanelCard {
                        title: "58.2 MODULAR RUNTIME BOUNDARY"
                        body: "QML owns presentation, Python owns orchestration and services, and C++20 owns deterministic low-latency primitives. Audio hardware remains single-owner behind the isolated PortAudio boundary."
                        metricLabel: "UI"
                        metric: "QML + Python + C++20"
                    }

                    PanelCard {
                        title: "57.10 COMPATIBILITY BASELINE"
                        body: "The frozen 57.10 engine remains the behavioral reference while functionality is moved behind service contracts. Script 58.2 does not replace or rewrite the verified capture pipeline."
                        metricLabel: "Migration"
                        metric: "additive"
                    }

                    PanelCard {
                        title: "THREADING POLICY"
                        body: "Presentation work stays on the Qt GUI thread. Long-running transcription work is dispatched through the Qt thread pool; QML never directly loads Whisper models."
                        metricLabel: "Presentation"
                        metric: "non-blocking"
                    }
                }
            }

            ScrollView {
                clip: true

                ColumnLayout {
                    width: parent.width
                    spacing: 12

                    PanelCard {
                        title: "RECORDING SERVICE"
                        body: "Script 58.2 establishes the presentation boundary without moving the 57.10 recording owner. The next extraction can expose the existing recording library through a model rather than direct widget ownership."
                        metricLabel: "57.10 rule"
                        metric: "15 s confirmed lock"
                    }

                    PanelCard {
                        title: "OWNERSHIP"
                        body: "QML must not enumerate microphones, write WAV files, apply retention rules, or manipulate the recording filesystem directly."
                    }
                }
            }

            Item {
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 12

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: 110
                        radius: 10
                        color: "#0b0f14"
                        border.color: "#294a55"

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 16
                            spacing: 16

                            ColumnLayout {
                                Layout.fillWidth: true

                                Label {
                                    text: "LOCAL TRANSCRIPTION SERVICE"
                                    font.family: "Oxanium"
                                    font.pixelSize: 18
                                    color: "#5fe7ef"
                                }

                                Label {
                                    text: "Backend: " + bci.transcriptionBackend
                                    font.family: "JetBrains Mono"
                                    color: "#dce6ec"
                                }

                                Label {
                                    text: "Model: " + bci.transcriptionModel
                                    font.family: "JetBrains Mono"
                                    color: "#8fa0aa"
                                    elide: Text.ElideMiddle
                                    Layout.fillWidth: true
                                }
                            }

                            Button {
                                text: "REFRESH"
                                enabled: !bci.transcriptionBusy
                                onClicked: bci.refreshTranscriptionBackend()
                            }

                            Button {
                                text: bci.transcriptionBusy ? "TRANSCRIBING…" : "TRANSCRIBE FILE"
                                enabled: !bci.transcriptionBusy && bci.transcriptionAvailable
                                onClicked: audioPicker.open()
                            }
                        }
                    }

                    ProgressBar {
                        Layout.fillWidth: true
                        from: 0
                        to: 100
                        value: bci.transcriptionProgress
                        indeterminate: bci.transcriptionBusy && bci.transcriptionProgress < 100
                    }

                    Label {
                        Layout.fillWidth: true
                        text: "STATUS: " + bci.transcriptionStatus
                        font.family: "JetBrains Mono"
                        color: bci.transcriptionStatus === "ERROR" ? "#ff7d8a" : "#78e5c5"
                    }

                    Label {
                        visible: bci.errorText.length > 0
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        text: bci.errorText
                        color: "#ff9a9f"
                    }

                    TextArea {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        readOnly: true
                        wrapMode: TextEdit.Wrap
                        text: bci.transcriptText.length > 0
                              ? bci.transcriptText
                              : "Select a recording to run the local transcription service."
                        font.family: "Rajdhani"
                        font.pixelSize: 17
                        color: "#e6edef"
                        background: Rectangle {
                            color: "#080c11"
                            border.color: "#294a55"
                            radius: 8
                        }
                    }
                }
            }

            ScrollView {
                clip: true

                ColumnLayout {
                    width: parent.width
                    spacing: 12

                    PanelCard {
                        title: "MASTERING SERVICE"
                        body: "The 57.10 mastering behavior remains authoritative during 58.1. QML will consume state and commands from the mastering service after extraction rather than applying DSP inside the presentation layer."
                        metricLabel: "Target"
                        metric: "-14 LUFS / -1 dBTP"
                    }

                    PanelCard {
                        title: "MIGRATION SAFETY"
                        body: "A subsystem moves behind the new boundary only after its output and lifecycle behavior match the frozen release contract."
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            height: 36
            color: "#080b10"
            border.color: "#471722"

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12

                Label {
                    text: "Developer Seal: CJB-DEV-2026"
                    font.family: "JetBrains Mono"
                    color: "#8fa0aa"
                }

                Item { Layout.fillWidth: true }

                Label {
                    text: "Observe accurately • Preserve faithfully • Analyze transparently • Communicate securely • Act deliberately"
                    font.family: "Rajdhani"
                    color: "#7e8c94"
                }
            }
        }
    }
}
