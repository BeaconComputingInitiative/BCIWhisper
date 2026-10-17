package org.beaconcomputinginitiative.bciwhisper

import android.Manifest
import android.app.Activity
import android.content.*
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.os.*
import android.view.Gravity
import android.view.ViewGroup
import android.widget.*
import org.beaconcomputinginitiative.bciwhisper.audio.AudioMonitorService
import java.util.Locale

class MainActivity : Activity() {
    private enum class Screen { MONITOR, RECORDINGS, TRANSCRIPTS, MASTERING }

    private val bg = Color.rgb(8, 10, 12)
    private val panel = Color.rgb(17, 23, 27)
    private val cyan = Color.rgb(0, 216, 230)
    private val maroon = Color.rgb(122, 23, 51)
    private val primaryText = Color.rgb(232, 241, 243)
    private val muted = Color.rgb(141, 160, 166)

    private val brandTypeface by lazy {
        runCatching { resources.getFont(R.font.oxanium_semibold) }
            .getOrElse { Typeface.create("sans-serif", Typeface.BOLD) }
    }
    private val uiTypeface by lazy {
        runCatching { resources.getFont(R.font.rajdhani_medium) }
            .getOrElse { Typeface.create("sans-serif-condensed", Typeface.NORMAL) }
    }
    private val dataTypeface by lazy {
        runCatching { resources.getFont(R.font.jetbrains_mono_regular) }
            .getOrElse { Typeface.MONOSPACE }
    }

    private var audioService: AudioMonitorService? = null
    private var bound = false
    private val handler = Handler(Looper.getMainLooper())

    private lateinit var content: FrameLayout
    private lateinit var monitorTab: Button
    private lateinit var recordingsTab: Button
    private lateinit var transcriptsTab: Button
    private lateinit var masteringTab: Button

    private var stateText: TextView? = null
    private var levelText: TextView? = null
    private var baselineText: TextView? = null
    private var baselineBar: ProgressBar? = null
    private var levelBar: ProgressBar? = null
    private var startButton: Button? = null
    private var stopButton: Button? = null

    private var currentScreen = Screen.MONITOR

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {
            audioService = (binder as? AudioMonitorService.LocalBinder)?.service()
            bound = audioService != null
            renderSnapshot()
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            bound = false
            audioService = null
            renderSnapshot()
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
        window.statusBarColor = bg
        window.navigationBarColor = bg
        setContentView(buildShell())
        requestPermissionsIfNeeded()
        showScreen(Screen.MONITOR)
    }

    override fun onStart() {
        super.onStart()
        bindAudioService()
        handler.post(poll)
    }

    override fun onStop() {
        handler.removeCallbacks(poll)
        if (bound) {
            unbindService(connection)
            bound = false
        }
        audioService = null
        super.onStop()
    }

    private fun bindAudioService() {
        if (!bound) {
            bindService(
                Intent(this, AudioMonitorService::class.java),
                connection,
                BIND_AUTO_CREATE
            )
        }
    }

    private fun requestPermissionsIfNeeded() {
        val needed = mutableListOf<String>()
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            needed += Manifest.permission.RECORD_AUDIO
        }
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            needed += Manifest.permission.POST_NOTIFICATIONS
        }
        if (needed.isNotEmpty()) requestPermissions(needed.toTypedArray(), 100)
    }

    private fun startMonitor() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 100)
            return
        }

        val intent = Intent(this, AudioMonitorService::class.java)
            .setAction(AudioMonitorService.ACTION_START)
        startForegroundService(intent)
        bindAudioService()
    }

    private fun stopMonitor() {
        startService(
            Intent(this, AudioMonitorService::class.java)
                .setAction(AudioMonitorService.ACTION_STOP)
        )
    }

    private fun buildShell(): LinearLayout {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(bg)
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        }

        val header = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(18), dp(20), dp(12))
            setBackgroundColor(bg)
        }

        header.addView(TextView(this).apply {
            text = "BCIWhisper"
            textSize = 28f
            setTextColor(cyan)
            typeface = brandTypeface
        })

        header.addView(TextView(this).apply {
            text = "ANDROID • v6.0 PORT"
            textSize = 11f
            setTextColor(muted)
            typeface = uiTypeface
        })

        root.addView(header)

        val tabs = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(dp(12), 0, dp(12), dp(10))
            setBackgroundColor(bg)
        }

        monitorTab = tabButton("MONITOR", Screen.MONITOR)
        recordingsTab = tabButton("RECORDINGS", Screen.RECORDINGS)
        transcriptsTab = tabButton("TRANSCRIPTS", Screen.TRANSCRIPTS)
        masteringTab = tabButton("MASTERING", Screen.MASTERING)

        listOf(monitorTab, recordingsTab, transcriptsTab, masteringTab).forEach {
            tabs.addView(
                it,
                LinearLayout.LayoutParams(0, dp(44), 1f).apply {
                    setMargins(dp(3), 0, dp(3), 0)
                }
            )
        }

        root.addView(tabs)

        content = FrameLayout(this).apply {
            setBackgroundColor(bg)
        }
        root.addView(
            content,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                0,
                1f
            )
        )

        return root
    }

    private fun tabButton(label: String, screen: Screen) = Button(this).apply {
        text = label
        textSize = 9.5f
        isAllCaps = false
        setTextColor(primaryText)
        typeface = uiTypeface
        setBackgroundColor(panel)
        setPadding(dp(2), 0, dp(2), 0)
        setOnClickListener { showScreen(screen) }
    }

    private fun showScreen(screen: Screen) {
        currentScreen = screen
        content.removeAllViews()

        listOf(
            monitorTab to Screen.MONITOR,
            recordingsTab to Screen.RECORDINGS,
            transcriptsTab to Screen.TRANSCRIPTS,
            masteringTab to Screen.MASTERING
        ).forEach { (button, target) ->
            button.setTextColor(if (target == screen) cyan else muted)
            button.setBackgroundColor(if (target == screen) Color.rgb(22, 42, 48) else panel)
        }

        val view = when (screen) {
            Screen.MONITOR -> buildMonitorScreen()
            Screen.RECORDINGS -> buildPendingScreen(
                "RECORDINGS",
                "Captured events will be organized here as logical recordings with preserved source audio and derived processing stages.",
                "Android recording-library port is the next functional stage."
            )
            Screen.TRANSCRIPTS -> buildPendingScreen(
                "TRANSCRIPTS",
                "Transcription remains operator initiated. This workspace will list completed and pending transcript jobs without coupling speech recognition to capture.",
                "Manual transcription backend is not enabled in this Android baseline yet."
            )
            Screen.MASTERING -> buildPendingScreen(
                "MASTERING",
                "The Android mastering workspace will remain non-destructive: original capture stays preserved while preview and mastered derivatives are created separately.",
                "Reconstruction and mastering DSP are not enabled in this Android baseline yet."
            )
        }

        content.addView(
            view,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        )
        renderSnapshot()
    }

    private fun buildMonitorScreen(): ScrollView {
        stateText = null
        levelText = null
        baselineText = null
        baselineBar = null
        levelBar = null
        startButton = null
        stopButton = null

        val scroll = ScrollView(this).apply {
            isFillViewport = true
            setBackgroundColor(bg)
        }

        val body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(8), dp(18), dp(30))
        }

        body.addView(sectionLabel("MICROPHONE"))

        val statusCard = card()
        stateText = textView("Boundary stopped", 16f, primaryText, role = FontRole.UI, bold = true)
        statusCard.addView(stateText)

        val statusHint = textView(
            "Start Monitor to open the Android microphone boundary. Capture continues in a foreground service while this screen is visible or backgrounded.",
            12f,
            muted
        )
        statusHint.setPadding(0, dp(8), 0, 0)
        statusCard.addView(statusHint)
        body.addView(statusCard)

        body.addView(sectionLabel("LIVE LEVEL").apply { setPadding(0, dp(20), 0, dp(8)) })

        val signalCard = card()
        levelText = textView("RMS -120.0 dBFS   •   PEAK -120.0 dBFS", 15f, primaryText, role = FontRole.DATA)
        signalCard.addView(levelText)

        levelBar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 600
            progress = 0
        }
        signalCard.addView(
            levelBar,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(18)
            ).apply { setMargins(0, dp(10), 0, 0) }
        )
        body.addView(signalCard)

        body.addView(sectionLabel("ROOM BASELINE").apply { setPadding(0, dp(20), 0, dp(8)) })

        val baselineCard = card()
        baselineText = textView("Baseline 0.0 / 60.0 s", 15f, primaryText, role = FontRole.DATA)
        baselineCard.addView(baselineText)

        baselineBar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 600
            progress = 0
        }
        baselineCard.addView(
            baselineBar,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(18)
            ).apply { setMargins(0, dp(10), 0, dp(8)) }
        )

        baselineCard.addView(
            textView(
                "The 60-second baseline runs without blocking the interface.",
                12f,
                muted
            )
        )
        body.addView(baselineCard)

        val controls = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            setPadding(0, dp(22), 0, dp(6))
        }

        startButton = Button(this).apply {
            text = "START MONITOR"
            setTextColor(Color.WHITE)
            typeface = uiTypeface
            setBackgroundColor(maroon)
            setOnClickListener { startMonitor() }
        }

        stopButton = Button(this).apply {
            text = "STOP"
            setTextColor(primaryText)
            typeface = uiTypeface
            setBackgroundColor(panel)
            isEnabled = false
            setOnClickListener { stopMonitor() }
        }

        controls.addView(
            startButton,
            LinearLayout.LayoutParams(0, dp(52), 2f).apply {
                setMargins(0, 0, dp(6), 0)
            }
        )
        controls.addView(
            stopButton,
            LinearLayout.LayoutParams(0, dp(52), 1f).apply {
                setMargins(dp(6), 0, 0, 0)
            }
        )

        body.addView(controls)

        body.addView(sectionLabel("ANDROID PORT STATUS").apply { setPadding(0, dp(22), 0, dp(8)) })

        val portCard = card()
        portCard.addView(
            textView(
                "✓ Native AudioRecord hardware boundary\n" +
                "✓ Foreground microphone service\n" +
                "✓ 44.1 kHz mono PCM16 capture\n" +
                "✓ Bounded 15-second circular ring\n" +
                "✓ Live RMS / peak telemetry\n" +
                "✓ 60-second baseline clock\n" +
                "○ Detector / lock logic pending\n" +
                "○ Recording library pending\n" +
                "○ Reconstruction / mastering pending\n" +
                "○ Manual transcription pending\n" +
                "○ Go Live publisher pending",
                13f,
                primaryText
            )
        )
        body.addView(portCard)

        body.addView(
            textView(
                "Observe accurately. Preserve faithfully. Analyze transparently. Communicate securely. Act deliberately.",
                11f,
                muted
            ).apply { setPadding(0, dp(28), 0, 0) }
        )

        scroll.addView(body)
        return scroll
    }

    private fun buildPendingScreen(title: String, bodyText: String, note: String): ScrollView {
        val scroll = ScrollView(this).apply {
            setBackgroundColor(bg)
        }
        val body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(14), dp(18), dp(30))
        }

        body.addView(sectionLabel(title))
        val c = card()
        c.addView(textView(bodyText, 16f, primaryText))
        c.addView(textView(note, 12f, muted).apply { setPadding(0, dp(16), 0, 0) })
        body.addView(c)

        body.addView(
            textView(
                "This screen is intentionally present before the subsystem is enabled so the mobile workflow remains stable while functionality is ported behind it.",
                12f,
                muted
            ).apply { setPadding(0, dp(20), 0, 0) }
        )

        scroll.addView(body)
        return scroll
    }

    private fun card() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(16), dp(16), dp(16), dp(16))
        setBackgroundColor(panel)
    }

    private fun sectionLabel(label: String) = TextView(this).apply {
        text = label
        textSize = 12f
        setTextColor(maroon)
        typeface = brandTypeface
        letterSpacing = 0.08f
        setPadding(0, dp(8), 0, dp(8))
    }

    private enum class FontRole { BRAND, UI, DATA }

    private fun textView(
        value: String,
        size: Float,
        color: Int,
        role: FontRole = FontRole.UI,
        bold: Boolean = false
    ) = TextView(this).apply {
        text = value
        textSize = size
        setTextColor(color)
        typeface = when (role) {
            FontRole.BRAND -> brandTypeface
            FontRole.UI -> if (bold) Typeface.create(uiTypeface, Typeface.BOLD) else uiTypeface
            FontRole.DATA -> dataTypeface
        }
        setLineSpacing(0f, 1.12f)
    }

    private fun renderSnapshot() {
        if (currentScreen != Screen.MONITOR) return

        val s = audioService?.snapshot()
        if (s == null) {
            stateText?.text = if (bound) "Microphone boundary ready" else "Boundary stopped"
            startButton?.isEnabled = true
            stopButton?.isEnabled = false
            return
        }

        stateText?.text = when {
            s.lastError != null -> "ERROR • ${s.lastError}"
            s.running && !s.baselineComplete -> "CALIBRATING • ${s.sampleRate} Hz"
            s.running -> "MONITORING • ${s.sampleRate} Hz"
            else -> "Boundary stopped"
        }

        levelText?.text = String.format(
            Locale.US,
            "RMS %.1f dBFS   •   PEAK %.1f dBFS",
            s.rmsDbfs,
            s.peakDbfs
        )

        val peakForMeter = s.peakDbfs.coerceIn(-60.0, 0.0)
        levelBar?.progress = ((peakForMeter + 60.0) * 10.0).toInt().coerceIn(0, 600)

        baselineText?.text = if (s.baselineComplete) {
            "Baseline complete • 60.0 s"
        } else {
            String.format(Locale.US, "Baseline %.1f / 60.0 s", s.baselineSeconds)
        }

        baselineBar?.progress = (s.baselineSeconds * 10.0).toInt().coerceIn(0, 600)
        startButton?.isEnabled = !s.running
        stopButton?.isEnabled = s.running
    }

    private fun dp(value: Int): Int =
        (value * resources.displayMetrics.density).toInt()
}
