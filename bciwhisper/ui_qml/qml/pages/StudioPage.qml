// BEACON COMPUTING INITIATIVE
// BCIWhisper Podcast Lab | Studio Transport 59.1
// Developer Seal: CJB-DEV-2026
// File SHA-256: generated in packaged release manifest
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Label {
            text: "PODCAST LAB  /  STUDIO"
            font.family: "Oxanium"; font.pixelSize: 24; color: "#5fe7ef"
        }
        Label {
            text: "Studio foundation · existing capture, calibration and broadcasting services"
            font.family: "Rajdhani"; color: "#9db0b8"
        }
        RowLayout {
            Layout.fillWidth: true
            MetricTile { Layout.fillWidth: true; label: "MICROPHONE"; value: bci.sampleRate > 0 ? "CONNECTED" : "WAITING"; detail: bci.deviceName }
            MetricTile { Layout.fillWidth: true; label: "NOISE FLOOR"; value: bci.noiseFloorDb.toFixed(1) + " dBFS"; detail: bci.baselineComplete ? "calibrated" : "calibrating" }
            MetricTile { Layout.fillWidth: true; label: "SIGNAL"; value: bci.snrDb.toFixed(1) + " dB"; detail: bci.signalActive ? "active" : "ambient" }
            MetricTile { Layout.fillWidth: true; label: "BROADCAST"; value: bci.goLive ? "LIVE" : "OFFLINE"; detail: "Render Cloud" }
        }
        Rectangle {
            Layout.fillWidth: true; Layout.fillHeight: true
            radius: 12; color: "#080d12"; border.color: "#23323a"
            SpectrumView { anchors.fill: parent; anchors.margins: 14 }
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: "ROOM BASELINE"; font.family: "Oxanium"; color: "#9db0b8" }
            ProgressBar { Layout.fillWidth: true; from: 0; to: 1; value: bci.baselineProgress }
            Label { text: Math.round(bci.baselineProgress * 100) + "%"; color: "#dce6ec"; font.family: "JetBrains Mono" }
            Button {
                text: "RECALIBRATE"
                enabled: bci.sampleRate > 0 && !bci.recording && !bci.goLive
                onClicked: bci.recalibrateBaseline()
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            Button {
                text: bci.podcastRecording ? "● RECORDING" : "● RECORD"
                enabled: !bci.recording && bci.sampleRate > 0
                onClicked: bci.startPodcastRecording()
            }
            Button {
                text: "■ STOP & SAVE"
                enabled: bci.podcastRecording
                onClicked: bci.stopPodcastRecording()
            }
            Label {
                text: bci.podcastRecording ? "PODCAST TAKE IN PROGRESS" : "TRANSPORT READY"
                font.family: "JetBrains Mono"
                color: bci.podcastRecording ? "#ff767f" : "#78e5c5"
            }
            Item { Layout.fillWidth: true }
        }
        Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: "Manual podcast takes save raw and isolated WAV recordings. Independent microphone tracks and timeline editing remain future milestones."
            color: "#71838b"; font.family: "Rajdhani"
        }
    }
}
