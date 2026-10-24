// BEACON COMPUTING INITIATIVE
// BCIWhisper Podcast Lab | Spatial Studio 60.0
// Developer Seal: CJB-DEV-2026
// File SHA-256: generated in packaged release manifest
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    property bool enableThreeD: true
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Label {
            text: "STUDIO  //  CONTROL DECK"
            font.family: "Oxanium"; font.pixelSize: 24; color: "#5fe7ef"
        }
        Label {
            text: "NEURAL SIGNAL CHAMBER     •     DUAL INPUT CAPTURE     •     DIRECT BROADCAST"
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
            radius: 22
            border.width: 2
            border.color: "#4c8997"
            gradient: Gradient {
                GradientStop { position: 0; color: "#244d61" }
                GradientStop { position: 0.05; color: "#102634" }
                GradientStop { position: 1; color: "#040915" }
            }
            Rectangle {
                anchors.fill: parent
                anchors.margins: 13
                radius: 15
                border.color: "#244b5f"
                border.width: 2
                color: "#040b15"
                Loader {
                    id: spatialRenderer
                    anchors.fill: parent
                    anchors.margins: 3
                    active: true
                    source: enableThreeD ? "../components/SignalObservatory3D.qml" : "../components/SpatialChamber.qml"
                    onStatusChanged: {
                        if (status === Loader.Error && enableThreeD)
                            enableThreeD = false
                    }
                }
                Rectangle {
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 18
                    radius: 7
                    width: modeButton.implicitWidth + 20
                    height: 36
                    color: "#142b3a"
                    border.color: "#4a8694"
                    Button {
                        id: modeButton
                        anchors.fill: parent
                        text: enableThreeD ? "3D / SWITCH TO 2D" : "2D / TRY 3D"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 10
                        onClicked: enableThreeD = !enableThreeD
                    }
                }
            }
            Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 29; height: 2; color: "#7eebf6"; opacity: .5 }
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
            Label {
                text: "STREAM QUEUE " + bci.streamQueueDepth + "  /  DROPS " + bci.streamDroppedChunks
                font.family: "JetBrains Mono"
                color: bci.streamDroppedChunks > 0 ? "#ff858e" : "#78e5c5"
            }
            Item { Layout.fillWidth: true }
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: "PROGRAM GAIN"; color: "#c3d5db"; font.family: "Oxanium" }
            Slider {
                id: programGainControl
                Layout.fillWidth: true
                from: 0; to: 2
                value: bci.programGain
                onMoved: bci.configureProgramBus(value, bci.programMuted)
            }
            Label { text: bci.programGain.toFixed(2) + "×"; color: "#8ee3ec"; font.family: "JetBrains Mono" }
            CheckBox {
                text: "MUTE PROGRAM"
                checked: bci.programMuted
                onClicked: bci.configureProgramBus(bci.programGain, checked)
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: "SECONDARY MIC"; font.family: "Oxanium"; color: "#c3d5db" }
            ComboBox {
                id: secondaryDevice
                Layout.preferredWidth: 260
                model: bci.devices
                textRole: "name"
                valueRole: "id"
                enabled: !bci.secondaryRunning && !bci.multitrackRecording
            }
            Button {
                text: bci.secondaryRunning ? "MIC 2 CONNECTED" : "CONNECT MIC 2"
                enabled: !bci.secondaryRunning && secondaryDevice.currentIndex >= 0
                onClicked: bci.startSecondary(Number(secondaryDevice.currentValue))
            }
            Button {
                text: "DISCONNECT MIC 2"
                enabled: bci.secondaryRunning && !bci.multitrackRecording
                onClicked: bci.stopSecondary()
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Button {
                text: "START 2-TRACK"
                enabled: bci.secondaryRunning && bci.sampleRate > 0 && !bci.multitrackRecording
                onClicked: bci.startMultitrack()
            }
            Button {
                text: "STOP 2-TRACK"
                enabled: bci.multitrackRecording
                onClicked: bci.stopMultitrack()
            }
            Label {
                text: bci.multitrackRecording ? "PRIMARY + SECONDARY WAV ACTIVE" : "TWO INPUTS REQUIRED"
                font.family: "JetBrains Mono"
                color: bci.multitrackRecording ? "#7ce5c5" : "#82939c"
            }
        }
        Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: "Manual podcast takes save raw and isolated WAV recordings. Two microphone tracks and timeline metadata are available; drift correction and audio edit rendering remain under development."
            color: "#71838b"; font.family: "Rajdhani"
        }
    }
}
