// BEACON COMPUTING INITIATIVE
// BCIWhisper Futuristic Spatial Signal Chamber
// Developer Seal: CJB-DEV-2026
import QtQuick
import QtQuick.Controls

Item {
    id: chamber
    property real phase: 0
    property color cyan: "#5debf1"
    property color maroon: "#9e355a"
    clip: true
    Timer {
        interval: 50; running: chamber.visible; repeat: true
        onTriggered: { chamber.phase += 0.035; visual.requestPaint() }
    }
    Canvas {
        id: visual
        anchors.fill: parent
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        Connections { target: bci; function onRuntimeChanged() { visual.requestPaint() } }
        onPaint: {
            const c = getContext("2d")
            const w = width, h = height
            c.clearRect(0, 0, w, h)
            const bg = c.createLinearGradient(0, 0, w, h)
            bg.addColorStop(0, "#071621"); bg.addColorStop(.55, "#080f1b"); bg.addColorStop(1, "#1c0819")
            c.fillStyle = bg; c.fillRect(0, 0, w, h)
            const cx = w * .5, cy = h * .57, radius = Math.min(w * .29, h * .42)
            c.lineWidth = 1
            for (let k = 0; k < 8; k++) {
                const d = (k + 1) / 8
                c.strokeStyle = k % 2 ? "rgba(84,230,241,.14)" : "rgba(177,53,101,.17)"
                c.beginPath()
                c.ellipse(cx, cy + radius * .42 * d, radius * d * 1.3, radius * d * .3, 0, 0, Math.PI * 2)
                c.stroke()
            }
            for (let k = 0; k < 24; k++) {
                const a = k / 24 * Math.PI * 2
                c.strokeStyle = "rgba(78,209,229,.12)"
                c.beginPath(); c.moveTo(cx, cy + radius * .42)
                c.lineTo(cx + Math.cos(a) * radius * 1.3, cy + radius * .42 + Math.sin(a) * radius * .3)
                c.stroke()
            }
            const bins = bci.spectrumDb || []
            const n = 48
            for (let i = 0; i < n; i++) {
                const a = (i / n) * Math.PI * 2 + phase * .10
                const db = bins.length ? Number(bins[Math.min(bins.length - 1, Math.floor(i * bins.length / n))]) : -120
                const level = Math.max(.04, Math.min(1, (db + 105) / 90))
                const orbit = radius * (.64 + .075 * Math.sin(phase + i * .41))
                const x = cx + Math.cos(a) * orbit, y = cy + Math.sin(a) * orbit * .38
                const length = 15 + level * radius * .50
                const rear = Math.sin(a) < 0
                c.strokeStyle = rear ? "rgba(91,224,237,.28)" : (i % 5 === 0 ? "#e8759d" : "#58e8ef")
                c.lineWidth = rear ? 1.4 : 2.1
                c.beginPath(); c.moveTo(x, y - length * .25); c.lineTo(x, y - length)
                c.stroke()
            }
            const glow = c.createRadialGradient(cx, cy - 16, 2, cx, cy - 16, radius * .7)
            glow.addColorStop(0, "rgba(79,220,236,.24)")
            glow.addColorStop(.6, "rgba(42,125,170,.09)")
            glow.addColorStop(1, "rgba(22,42,65,0)")
            c.fillStyle = glow; c.beginPath(); c.arc(cx, cy - 16, radius * .7, 0, Math.PI * 2); c.fill()
            for (let j = 0; j < 3; j++) {
                c.beginPath(); c.strokeStyle = j === 1 ? "rgba(234,91,143,.55)" : "rgba(97,224,237,.36)"
                c.lineWidth = j === 1 ? 1.8 : 1
                c.ellipse(cx, cy - radius * .22, radius * (.43 + j * .12),
                          radius * (.25 + j * .08), phase * .12 + j * .7, 0, Math.PI * 2)
                c.stroke()
            }
        }
    }
    Rectangle {
        anchors.left: parent.left; anchors.top: parent.top
        anchors.margins: 18; color: "#132535"; radius: 6; opacity: .9
        width: sourceText.implicitWidth + 20; height: 30
        Label {
            id: sourceText; anchors.centerIn: parent
            text: "◈   SPATIAL AUDIO / LIVE SIGNAL"
            font.family: "JetBrains Mono"; font.pixelSize: 10; color: "#a1edf5"
        }
    }
    Label {
        anchors.bottom: parent.bottom; anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottomMargin: 18
        text: bci.signalActive ? "SIGNAL DETECTED" : "SCANNING INPUT SPECTRUM"
        font.family: "Oxanium"; font.pixelSize: 13; font.letterSpacing: 2; color: "#94d7e4"
    }
}
