import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    property real lowcut: 80
    property real highcut: 8000
    property real gain: 1.0
    property real sensitivity: 1.0

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        ArchitectureCard {
            Layout.fillWidth: true
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: controls.implicitHeight + 32
            radius: 12
            color: "#090f15"
            border.color: "#23333c"

            ColumnLayout {
                id: controls
                anchors.fill: parent
                anchors.margins: 16
                spacing: 12

                RowLayout {
                    Layout.fillWidth: true

                    Label {
                        text: "INPUT DEVICE"
                        font.family: "Oxanium"
                        color: "#dfe9ec"
                    }

                    ComboBox {
                        id: deviceBox
                        Layout.fillWidth: true
                        model: bci.devices
                        textRole: "name"
                    }

                    Button {
                        text: "SELECT"
                        enabled: deviceBox.currentIndex >= 0
                        onClicked: {
                            const item = bci.devices[deviceBox.currentIndex]
                            bci.selectDevice(item.id, item.name, "explicit")
                        }
                    }

                    Button {
                        text: "SYSTEM DEFAULT"
                        onClicked: bci.selectDevice(-1, "", "auto")
                    }

                    Button {
                        text: "REFRESH"
                        onClicked: bci.refreshDevices()
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: 14
                    rowSpacing: 8

                    Label { text: "Low cut " + Math.round(lowcut) + " Hz"; color: "#91a2aa" }
                    Slider {
                        Layout.fillWidth: true
                        from: 20; to: 1000; value: lowcut
                        onMoved: lowcut = value
                    }

                    Label { text: "High cut " + Math.round(highcut) + " Hz"; color: "#91a2aa" }
                    Slider {
                        Layout.fillWidth: true
                        from: 1000; to: 20000; value: highcut
                        onMoved: highcut = value
                    }

                    Label { text: "Gain " + gain.toFixed(2) + "×"; color: "#91a2aa" }
                    Slider {
                        Layout.fillWidth: true
                        from: 0.25; to: 4.0; value: gain
                        onMoved: gain = value
                    }

                    Label { text: "Sensitivity " + sensitivity.toFixed(2) + "×"; color: "#91a2aa" }
                    Slider {
                        Layout.fillWidth: true
                        from: 0.25; to: 4.0; value: sensitivity
                        onMoved: sensitivity = value
                    }
                }

                Button {
                    text: "APPLY DSP PARAMETERS"
                    onClicked: bci.configureAudio(lowcut, highcut, gain, sensitivity)
                }
            }
        }

        Item { Layout.fillHeight: true }
    }
}
