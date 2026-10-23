// BEACON COMPUTING INITIATIVE
// BCIWhisper Script 58.2 | Engineering Build 2026.10.22-r6.35.2
// Developer Seal: CJB-DEV-2026

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root

    Layout.fillWidth: true
    implicitHeight: content.implicitHeight + 34
    radius: 12
    color: "#090e14"
    border.width: 1
    border.color: bci.nativeLoaded ? "#2f7880" : "#6f5830"

    ColumnLayout {
        id: content
        anchors.fill: parent
        anchors.margins: 17
        spacing: 12

        RowLayout {
            Layout.fillWidth: true

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3

                Label {
                    text: "THREE-LANGUAGE RUNTIME"
                    font.family: "Oxanium"
                    font.pixelSize: 18
                    font.weight: Font.DemiBold
                    color: "#5fe7ef"
                }

                Label {
                    Layout.fillWidth: true
                    text: bci.architectureSummary
                    font.family: "JetBrains Mono"
                    font.pixelSize: 13
                    color: "#dbe6eb"
                    elide: Text.ElideRight
                }
            }

            Rectangle {
                implicitWidth: nativeState.implicitWidth + 22
                implicitHeight: 30
                radius: 15
                color: bci.nativeLoaded ? "#12363a" : "#3b301b"
                border.color: bci.nativeLoaded ? "#4ebbc3" : "#b18c42"

                Label {
                    id: nativeState
                    anchors.centerIn: parent
                    text: bci.nativeLoaded ? "C++20 ACTIVE" : "FALLBACK ACTIVE"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 11
                    font.weight: Font.Bold
                    color: bci.nativeLoaded ? "#83f1f5" : "#ffd98c"
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Repeater {
                model: [
                    { name: "QML / QT QUICK", detail: "PRESENTATION" },
                    { name: "PYTHON", detail: "SERVICES + LIFECYCLE" },
                    { name: "C++20", detail: "AUDIO / DSP PRIMITIVES" }
                ]

                delegate: Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: 62
                    radius: 8
                    color: "#0d141b"
                    border.color: "#263a44"

                    Column {
                        anchors.centerIn: parent
                        spacing: 3

                        Label {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: modelData.name
                            font.family: "Oxanium"
                            font.pixelSize: 13
                            color: "#e5edef"
                        }

                        Label {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: modelData.detail
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9
                            color: "#7f929c"
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true

            Label {
                Layout.fillWidth: true
                text: "Native self-test: " + bci.nativeSelfTest + "   •   " + bci.nativeMetrics
                font.family: "JetBrains Mono"
                font.pixelSize: 11
                color: bci.nativeSelfTest === "PASS" ? "#78e5c5" : "#ff9a9f"
                elide: Text.ElideRight
            }

            Button {
                text: "RUN NATIVE TEST"
                onClicked: bci.runNativeSelfTest()
            }
        }
    }
}
