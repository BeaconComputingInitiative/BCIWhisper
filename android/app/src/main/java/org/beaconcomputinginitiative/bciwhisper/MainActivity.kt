package org.beaconcomputinginitiative.bciwhisper

import android.Manifest
import android.app.Activity
import android.content.*
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.*
import android.view.Gravity
import android.view.ViewGroup
import android.widget.*
import org.beaconcomputinginitiative.bciwhisper.audio.AudioMonitorService
import java.util.Locale

class MainActivity : Activity() {
    private var audioService: AudioMonitorService? = null
    private var bound = false
    private val handler = Handler(Looper.getMainLooper())

    private lateinit var stateText: TextView
    private lateinit var levelText: TextView
    private lateinit var baselineText: TextView
    private lateinit var baselineBar: ProgressBar
    private lateinit var startButton: Button
    private lateinit var stopButton: Button

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {
            audioService = (binder as? AudioMonitorService.LocalBinder)?.service()
            bound = audioService != null
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            bound = false
            audioService = null
        }
    }

    private val poll = object : Runnable {
        override fun run() {
            renderSnapshot()
            handler.postDelayed(this, 100)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Color.rgb(8, 10, 12)
        window.navigationBarColor = Color.rgb(8, 10, 12)
        setContentView(buildUi())
        requestPermissionsIfNeeded()
    }

    override fun onStart() {
        super.onStart()
        bindService(Intent(this, AudioMonitorService::class.java), connection, BIND_AUTO_CREATE)
        handler.post(poll)
    }

    override fun onStop() {
        handler.removeCallbacks(poll)
        if (bound) unbindService(connection)
        bound = false
        audioService = null
        super.onStop()
    }

    private fun requestPermissionsIfNeeded() {
        val needed = mutableListOf<String>()
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            needed += Manifest.permission.RECORD_AUDIO
        }
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            needed += Manifest.permission.POST_NOTIFICATIONS
        }
        if (needed.isNotEmpty()) requestPermissions(needed.toTypedArray(), 100)
    }

    private fun startMonitor() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 100)
            return
        }
        val intent = Intent(this, AudioMonitorService::class.java).setAction(AudioMonitorService.ACTION_START)
        startForegroundService(intent)
        bindService(Intent(this, AudioMonitorService::class.java), connection, BIND_AUTO_CREATE)
    }

    private fun stopMonitor() {
        startService(Intent(this, AudioMonitorService::class.java).setAction(AudioMonitorService.ACTION_STOP))
    }

    private fun buildUi(): LinearLayout {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(36, 30, 36, 30)
            setBackgroundColor(Color.rgb(8, 10, 12))
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        }

        root.addView(TextView(this).apply {
            text = "BCIWhisper"
            textSize = 30f
            setTextColor(Color.rgb(0, 216, 230))
            setTypeface(typeface, android.graphics.Typeface.BOLD)
        })

        root.addView(TextView(this).apply {
            text = "ANDROID PORT • v6.0 • PHASE 1"
            textSize = 12f
            setTextColor(Color.rgb(141, 160, 166))
            setPadding(0, 0, 0, 28)
        })

        root.addView(sectionTitle("MONITOR"))

        stateText = valueText("Boundary stopped")
        root.addView(stateText)

        levelText = valueText("RMS -120.0 dBFS   PEAK -120.0 dBFS")
        root.addView(levelText)

        baselineText = valueText("Baseline 0.0 / 60.0 s")
        root.addView(baselineText)

        baselineBar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 600
            progress = 0
        }
        root.addView(
            baselineBar,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 20).apply {
                setMargins(0, 8, 0, 26)
            }
        )

        val buttonRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }

        startButton = Button(this).apply {
            text = "START MONITOR"
            setOnClickListener { startMonitor() }
        }

        stopButton = Button(this).apply {
            text = "STOP"
            setOnClickListener { stopMonitor() }
        }

        buttonRow.addView(
            startButton,
            LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        )
        buttonRow.addView(
            stopButton,
            LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        )
        root.addView(buttonRow)

        root.addView(sectionTitle("PORT STATUS").apply { setPadding(0, 36, 0, 10) })

        root.addView(
            valueText(
                "✓ Android AudioRecord hardware boundary\n" +
                "✓ Foreground microphone service\n" +
                "✓ 44.1 kHz mono PCM16 capture\n" +
                "✓ 15-second circular capture ring\n" +
                "✓ Live RMS / peak telemetry\n" +
                "✓ 60-second baseline clock\n" +
                "○ Detection / lock port pending\n" +
                "○ Recording library pending\n" +
                "○ Reconstruction / mastering pending\n" +
                "○ Manual transcription backend pending\n" +
                "○ Go Live publisher pending"
            )
        )

        root.addView(TextView(this).apply {
            text = "Observe accurately. Preserve faithfully. Analyze transparently. Communicate securely. Act deliberately."
            textSize = 11f
            setTextColor(Color.rgb(122, 23, 51))
            setPadding(0, 36, 0, 0)
        })

        return root
    }

    private fun sectionTitle(text: String) = TextView(this).apply {
        this.text = text
        textSize = 13f
        setTextColor(Color.rgb(122, 23, 51))
        setTypeface(typeface, android.graphics.Typeface.BOLD)
        setPadding(0, 10, 0, 10)
    }

    private fun valueText(text: String) = TextView(this).apply {
        this.text = text
        textSize = 15f
        setTextColor(Color.rgb(232, 241, 243))
        setPadding(0, 5, 0, 5)
    }

    private fun renderSnapshot() {
        val s = audioService?.snapshot()
        if (s == null) {
            stateText.text = if (bound) "Boundary connected" else "Boundary stopped"
            return
        }

        stateText.text = when {
            s.lastError != null -> "ERROR: ${s.lastError}"
            s.running -> "MICROPHONE BOUNDARY ACTIVE • ${s.sampleRate} Hz"
            else -> "Boundary stopped"
        }

        levelText.text = String.format(
            Locale.US,
            "RMS %.1f dBFS   PEAK %.1f dBFS",
            s.rmsDbfs,
            s.peakDbfs
        )

        baselineText.text = if (s.baselineComplete) {
            "Baseline COMPLETE • 60.0 s"
        } else {
            String.format(Locale.US, "Baseline %.1f / 60.0 s", s.baselineSeconds)
        }

        baselineBar.progress = (s.baselineSeconds * 10.0).toInt().coerceIn(0, 600)
        startButton.isEnabled = !s.running
        stopButton.isEnabled = s.running
    }
}
