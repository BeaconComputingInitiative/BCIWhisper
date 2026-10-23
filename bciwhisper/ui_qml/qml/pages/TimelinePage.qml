// BEACON COMPUTING INITIATIVE
// BCIWhisper 59.7–60.0 Timeline / Transcript Marker Workspace
// Developer Seal: CJB-DEV-2026
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Label { text: "EPISODE TIMELINE"; font.family: "Oxanium"; font.pixelSize: 22; color: "#5fe7ef" }
        Label {
            text: "Nondestructive source references and trim ranges; no audio is rewritten."
            color: "#9db0b8"
        }
        RowLayout {
            Layout.fillWidth: true
            TextField { id: sourcePath
                                    Layout.fillWidth: true; placeholderText: "Absolute path to existing mono WAV file" }
            Button { text: "IMPORT WAV"; onClicked: bci.importEpisodeTrack(sourcePath.text) }
        }
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Column {
                width: parent.width
                spacing: 8
                Repeater {
                    model: bci.episodeTracks
                    delegate: Rectangle {
                        required property var modelData
                        required property int index
                        width: parent.width
                        height: 132
                        radius: 8
                        color: "#111b23"
                        border.color: "#31515f"
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 8
                            Label { text: modelData.source; color: "#dae9ed"
                                elide: Text.ElideLeft
                                    Layout.fillWidth: true }
                            RowLayout {
                                TextField { id: startTime; text: modelData["in"].toFixed(2)
                                    validator: DoubleValidator { bottom: 0 }
                                    Layout.preferredWidth: 90 }
                                Label { text: "→"; color: "#5fe7ef" }
                                TextField { id: endTime; text: modelData.out.toFixed(2)
                                    validator: DoubleValidator { bottom: 0 }
                                    Layout.preferredWidth: 90 }
                                Button { text: "SET TRIM"; onClicked: bci.trimEpisodeTrack(index, Number(startTime.text), Number(endTime.text)) }
                                Label { text: modelData.rate + " Hz / " + modelData.frames + " frames"; color: "#8b9ca5" }
                            }
                            RowLayout {
                                Label { text: "TRACK GAIN"; color: "#a3bac2" }
                                Slider {
                                    Layout.preferredWidth: 190
                                    from: 0; to: 2
                                    value: modelData.gain
                                    onMoved: bci.setEpisodeTrackMix(index, value, modelData.muted)
                                }
                                CheckBox {
                                    text: "MUTE"
                                    checked: modelData.muted
                                    onClicked: bci.setEpisodeTrackMix(index, modelData.gain, checked)
                                }
                            }
                        }
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            TextField { id: markerSeconds; placeholderText: "Marker seconds"
                                    validator: DoubleValidator { bottom: 0 }
                                    Layout.preferredWidth: 130 }
            TextField { id: markerText; placeholderText: "Transcript cue or note"
                                    Layout.fillWidth: true }
            Button { text: "ADD CUE"; onClicked: bci.addEpisodeMarker(Number(markerSeconds.text), markerText.text) }
        }
        RowLayout {
            Layout.fillWidth: true
            TextField { id: projectPath
                                    Layout.fillWidth: true; placeholderText: "Episode .json project path" }
            Button { text: "SAVE PROJECT"; onClicked: bci.saveEpisode(projectPath.text) }
            Button { text: "OPEN PROJECT"; onClicked: bci.loadEpisode(projectPath.text) }
        }
        Label { text: "60.0 foundation: transcript cues; time-coded Whisper word edits still need service integration."; color: "#7d929e" }
    }
}
