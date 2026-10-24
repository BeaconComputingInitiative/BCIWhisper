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
