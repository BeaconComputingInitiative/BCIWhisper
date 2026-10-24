// BEACON COMPUTING INITIATIVE
// BCIWhisper Qt Quick 3D Signal Observatory
// Developer Seal: CJB-DEV-2026
import QtQuick
import QtQuick3D

Item {
    id: observatory
    property real rotationAngle: 0
    property bool animated: true
    property real amplitude: Math.max(0.04, Math.min(1.0, (bci.snrDb + 3) / 42))
    Timer {
        interval: 50
        running: observatory.visible && observatory.animated
        repeat: true
        onTriggered: observatory.rotationAngle = (observatory.rotationAngle + 0.42) % 360
    }
    View3D {
        anchors.fill: parent
        environment: SceneEnvironment {
            clearColor: "#050b14"
            backgroundMode: SceneEnvironment.Color
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.Medium
        }
        PerspectiveCamera {
            id: orbitCamera
            position: Qt.vector3d(0, 165, 640)
            eulerRotation.x: -12
            clipFar: 3000
        }
        camera: orbitCamera
        DirectionalLight {
            eulerRotation: Qt.vector3d(-35, -35, 0)
            brightness: 1.1
            ambientColor: "#214b59"
            color: "#83efff"
        }
        PointLight {
            position: Qt.vector3d(-200, 130, 100)
            brightness: 70
            color: "#db5688"
        }
        Node {
            eulerRotation.y: observatory.rotationAngle
            Model {
                source: "#Sphere"
                scale: Qt.vector3d(1.55, 1.55, 1.55)
                materials: PrincipledMaterial {
                    baseColor: "#11394c"
                    metalness: 0.7
                    roughness: 0.22
                    emissiveFactor: Qt.vector3d(0.1, 0.22, 0.3)
                }
            }
            Repeater3D {
                model: 36
                delegate: Model {
                    required property int index
                    readonly property real theta: index * Math.PI * 2 / 36
                    readonly property var bins: bci.spectrumDb
                    readonly property real db: bins.length ? Number(bins[Math.min(bins.length - 1, Math.floor(index * bins.length / 36))]) : -110
                    readonly property real energy: Math.max(.05, Math.min(1, (db + 105) / 85))
                    source: "#Cylinder"
                    position: Qt.vector3d(Math.cos(theta) * 210, -45 + energy * 45,
                                          Math.sin(theta) * 210)
                    scale: Qt.vector3d(.12, .3 + energy * 1.5, .12)
                    materials: PrincipledMaterial {
                        baseColor: index % 6 === 0 ? "#ca467d" : "#49d7e8"
                        metalness: 0.48
                        roughness: 0.25
                        emissiveFactor: Qt.vector3d(0.12, 0.3, 0.33)
                    }
                }
            }
            Repeater3D {
                model: 3
                delegate: Model {
                    required property int index
                    source: "#Torus"
                    eulerRotation: Qt.vector3d(65 + index * 12, index * 35, 0)
                    scale: Qt.vector3d(2.65 + index * .32, 2.65 + index * .32, 2.65 + index * .32)
                    materials: PrincipledMaterial {
                        baseColor: index === 1 ? "#ac3a69" : "#2e8a9a"
                        metalness: .85
                        roughness: .2
                    }
                }
            }
        }
        Model {
            source: "#Cube"
            position: Qt.vector3d(0, -145, 0)
            scale: Qt.vector3d(7.4, .08, 6.1)
            materials: PrincipledMaterial {
                baseColor: "#091827"
                metalness: .6
                roughness: .38
            }
        }
    }
}
