import QtQuick

Canvas {
    id: root

    Connections {
        target: bci
        function onRuntimeChanged() { root.requestPaint() }
    }

    onPaint: {
        const ctx = getContext("2d")
        ctx.clearRect(0, 0, width, height)
        ctx.fillStyle = "#060a0f"
        ctx.fillRect(0, 0, width, height)

        ctx.strokeStyle = "#17242c"
        ctx.lineWidth = 1
        for (let i = 1; i < 6; ++i) {
            const y = i * height / 6
            ctx.beginPath()
            ctx.moveTo(0, y)
            ctx.lineTo(width, y)
            ctx.stroke()
        }

        const values = bci.spectrumDb
        if (!values || values.length < 2)
            return

        let minDb = -120
        let maxDb = 0
        ctx.strokeStyle = "#53d8e4"
        ctx.lineWidth = 1.5
        ctx.beginPath()

        for (let i = 0; i < values.length; ++i) {
            const x = i * width / Math.max(1, values.length - 1)
            const clamped = Math.max(minDb, Math.min(maxDb, Number(values[i])))
            const normalized = (clamped - minDb) / (maxDb - minDb)
            const y = height - normalized * height
            if (i === 0)
                ctx.moveTo(x, y)
            else
                ctx.lineTo(x, y)
        }
        ctx.stroke()
    }
}
