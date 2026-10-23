import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            MetricTile {
                Layout.fillWidth: true
                label: "RMS"
                value: bci.rms.toFixed(4)
                detail: bci.signalActive ? "signal active" : "ambient"
            }
            MetricTile {
                Layout.fillWidth: true
                label: "PEAK"
                value: bci.peak.toFixed(4)
                detail: bci.peakFrequency.toFixed(0) + " Hz"
            }
            MetricTile {
                Layout.fillWidth: true
                label: "SNR"
                value: bci.snrDb.toFixed(1) + " dB"
                detail: "noise " + bci.noiseFloorDb.toFixed(1) + " dBFS"
            }
            MetricTile {
                Layout.fillWidth: true
                label: "CAPTURE"
                value: bci.sampleRate > 0 ? bci.sampleRate + " Hz" : "WAITING"
                detail: bci.deviceName
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 12
            color: "#080d12"
            border.color: bci.signalActive ? "#2c7b67" : "#23323a"

            SpectrumView {
                anchors.fill: parent
                anchors.margins: 12
            }
        }

        RowLayout {
            Layout.fillWidth: true

            Label {
                text: "BASELINE"
                font.family: "Oxanium"
                color: "#7f939c"
            }

            ProgressBar {
                Layout.fillWidth: true
                from: 0
                to: 1
                value: bci.baselineProgress
            }

            Label {
                text: Math.round(bci.baselineProgress * 100) + "%"
                font.family: "JetBrains Mono"
                color: bci.baselineComplete ? "#78e5c5" : "#d6e1e5"
            }

            Button {
                text: "RECALIBRATE"
                enabled: bci.sampleRate > 0 && !bci.recording && !bci.goLive
                onClicked: bci.recalibrateBaseline()
                ToolTip.visible: hovered
                ToolTip.text: "Capture a fresh 60-second room-noise baseline"
            }

            Label {
                text: bci.recording ? "● RECORDING" : "MONITORING"
                font.family: "JetBrains Mono"
                color: bci.recording ? "#ff6d77" : "#73909a"
            }
        }
    }
}
