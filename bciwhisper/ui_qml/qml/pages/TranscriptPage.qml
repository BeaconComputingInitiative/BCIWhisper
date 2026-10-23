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
                text: "LOCAL TRANSCRIPTION"
                font.family: "Oxanium"
                font.pixelSize: 18
                color: "#5fe7ef"
            }

            Item { Layout.fillWidth: true }

            Label {
                text: bci.transcriptStatus
                font.family: "JetBrains Mono"
                color: bci.transcriptStatus === "ERROR" ? "#ff7f89" : "#7be4c6"
            }
        }

        RowLayout {
            Layout.fillWidth: true

            Label {
                text: "Backend: " + (bci.transcriptBackend || "—")
                font.family: "JetBrains Mono"
                color: "#82949d"
            }

            Label {
                Layout.fillWidth: true
                text: "Model: " + (bci.transcriptModel || "—")
                font.family: "JetBrains Mono"
                color: "#82949d"
                elide: Text.ElideMiddle
            }
        }

        TextArea {
            Layout.fillWidth: true
            Layout.fillHeight: true
            readOnly: true
            wrapMode: TextEdit.Wrap
            text: bci.transcriptText.length > 0
                  ? bci.transcriptText
                  : "Choose TRANSCRIBE on a recording to run the local Whisper service."
            font.family: "Rajdhani"
            font.pixelSize: 18
            color: "#e8eff1"
            background: Rectangle {
                radius: 10
                color: "#080d12"
                border.color: "#22333d"
            }
        }
    }
}
