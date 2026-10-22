// BEACON COMPUTING INITIATIVE
// BCIWhisper Script 58.1 | Engineering Build 2026.10.22-r6.35.1
// Developer Seal: CJB-DEV-2026
// Canonical Payload SHA-256: f316e7f256557f69628fc1fc4bb469f6d0642d027817ad50dfe1a63278305a05
// Integrity rule: hash covers this file's payload below this header, if and only if the payload is unchanged.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root

    property alias title: titleLabel.text
    property alias body: bodyLabel.text
    property string metric: ""
    property string metricLabel: ""

    Layout.fillWidth: true
    implicitHeight: content.implicitHeight + 30
    radius: 10
    color: "#0b0f14"
    border.color: "#294a55"
    border.width: 1

    ColumnLayout {
        id: content
        anchors.fill: parent
        anchors.margins: 15
        spacing: 8

        Label {
            id: titleLabel
            Layout.fillWidth: true
            font.family: "Oxanium"
            font.pixelSize: 17
            font.weight: Font.DemiBold
            color: "#5fe7ef"
        }

        Label {
            id: bodyLabel
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            font.family: "Rajdhani"
            font.pixelSize: 15
            color: "#c9d5dc"
        }

        RowLayout {
            visible: root.metric.length > 0
            Layout.fillWidth: true

            Label {
                text: root.metricLabel
                font.family: "JetBrains Mono"
                color: "#8a9aa5"
            }

            Item { Layout.fillWidth: true }

            Label {
                text: root.metric
                font.family: "JetBrains Mono"
                color: "#f0f5f6"
            }
        }
    }
}
