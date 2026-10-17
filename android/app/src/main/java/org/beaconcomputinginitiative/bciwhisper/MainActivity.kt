package org.beaconcomputinginitiative.bciwhisper

import android.Manifest
import android.app.Activity
import android.content.*
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.*
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.view.ViewGroup
import android.widget.*
import org.beaconcomputinginitiative.bciwhisper.audio.AudioMonitorService
import org.beaconcomputinginitiative.bciwhisper.audio.ReconstructionMasteringEngine
import org.beaconcomputinginitiative.bciwhisper.broadcast.BroadcastPublisher
import org.beaconcomputinginitiative.bciwhisper.transcription.TranscriptionEngine
import java.util.Locale

class MainActivity : Activity() {
    private enum class Screen {
        MONITOR,
        RECORDINGS,
        TRANSCRIPTS,
        MASTERING
    }

    private enum class FontRole {
        BRAND,
        UI,
        DATA
    }

    private val bg = Color.rgb(8, 10, 12)
    private val panel = Color.rgb(17, 23, 27)
    private val cyan = Color.rgb(0, 216, 230)
    private val maroon = Color.rgb(122, 23, 51)
    private val primaryText = Color.rgb(232, 241, 243)
    private val muted = Color.rgb(141, 160, 166)

    private val prefs by lazy {
        getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
    }

    private val brandTypeface by lazy {
        runCatching {
            resources.getFont(R.font.oxanium_semibold)
        }.getOrElse {
            Typeface.create("sans-serif", Typeface.BOLD)
        }
    }

    private val uiTypeface by lazy {
        runCatching {
            resources.getFont(R.font.rajdhani_medium)
        }.getOrElse {
            Typeface.create("sans-serif-condensed", Typeface.NORMAL)
        }
    }

    private val dataTypeface by lazy {
        runCatching {
            resources.getFont(R.font.jetbrains_mono_regular)
        }.getOrElse {
            Typeface.MONOSPACE
        }
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
    private var permissionText: TextView? = null
    private var levelText: TextView? = null
    private var baselineText: TextView? = null
    private var baselineBar: ProgressBar? = null
    private var levelBar: ProgressBar? = null
    private var detectionText: TextView? = null
    private var startButton: Button? = null
    private var stopButton: Button? = null
    private var phoneSourceButton: Button? = null
    private var bluetoothSourceButton: Button? = null
    private var sourceStatusText: TextView? = null
    private var pendingBluetoothSelection = false

    private var networkText: TextView? = null
    private var gatewayEdit: EditText? = null
    private var tokenEdit: EditText? = null
    private var broadcastStatusText: TextView? = null
    private var goLiveButton: Button? = null
    private var stopLiveButton: Button? = null

    private val transcriptionEngine by lazy { TranscriptionEngine(this) }
    private val masteringEngine by lazy { ReconstructionMasteringEngine() }
    @Volatile private var transcriptionBusy = false
    @Volatile private var masteringBusy = false

    private var currentScreen = Screen.MONITOR

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(
            name: ComponentName?,
            binder: IBinder?
        ) {
            audioService =
                (binder as? AudioMonitorService.LocalBinder)?.service()
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
            handler.postDelayed(this, 250)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        window.statusBarColor = bg
        window.navigationBarColor = bg

        setContentView(buildShell())
        showScreen(Screen.MONITOR)
        maybeRequestMicrophonePermissionOnce()
    }

    override fun onStart() {
        super.onStart()
        bindAudioService()
        handler.post(poll)
    }

    override fun onResume() {
        super.onResume()
        renderSnapshot()
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

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(
            requestCode,
            permissions,
            grantResults
        )

        if (requestCode == REQUEST_MICROPHONE) {
            renderSnapshot()

            if (!hasMicrophonePermission()) {
                Toast.makeText(
                    this,
                    "Microphone access was not enabled. " +
                        "BCIWhisper will not ask again automatically.",
                    Toast.LENGTH_LONG
                ).show()
            }
        }

        if (requestCode == REQUEST_BLUETOOTH_CONNECT) {
            if (hasBluetoothPermission() && pendingBluetoothSelection) {
                selectInputSource(AudioMonitorService.INPUT_SOURCE_BLUETOOTH)
            } else if (!hasBluetoothPermission()) {
                Toast.makeText(
                    this,
                    "Nearby devices access was not enabled. BCIWhisper will not ask again automatically.",
                    Toast.LENGTH_LONG
                ).show()
            }
            pendingBluetoothSelection = false
            renderInputSourceControls()
        }
    }

    private fun hasBluetoothPermission(): Boolean =
        Build.VERSION.SDK_INT < 31 ||
            checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) ==
            PackageManager.PERMISSION_GRANTED

    private fun requestBluetoothSource() {
        if (Build.VERSION.SDK_INT < 31 || hasBluetoothPermission()) {
            selectInputSource(AudioMonitorService.INPUT_SOURCE_BLUETOOTH)
            return
        }

        if (prefs.getBoolean(KEY_BLUETOOTH_PROMPTED, false)) {
            Toast.makeText(
                this,
                "Enable Nearby devices for BCIWhisper in App permissions.",
                Toast.LENGTH_LONG
            ).show()
            openAppPermissionSettings()
            return
        }

        pendingBluetoothSelection = true
        prefs.edit().putBoolean(KEY_BLUETOOTH_PROMPTED, true).apply()
        requestPermissions(
            arrayOf(Manifest.permission.BLUETOOTH_CONNECT),
            REQUEST_BLUETOOTH_CONNECT
        )
    }

    private fun selectedInputSource(): String =
        prefs.getString(KEY_INPUT_SOURCE, AudioMonitorService.INPUT_SOURCE_PHONE)
            ?.takeIf {
                it == AudioMonitorService.INPUT_SOURCE_PHONE ||
                    it == AudioMonitorService.INPUT_SOURCE_BLUETOOTH
            }
            ?: AudioMonitorService.INPUT_SOURCE_PHONE

    private fun selectInputSource(source: String) {
        if (audioService?.snapshot()?.running == true) {
            Toast.makeText(
                this,
                "Stop monitoring before changing the microphone source.",
                Toast.LENGTH_LONG
            ).show()
            return
        }

        prefs.edit().putString(KEY_INPUT_SOURCE, source).apply()
        renderInputSourceControls()
    }

    private fun renderInputSourceControls() {
        val selected = selectedInputSource()
        val running = audioService?.snapshot()?.running == true

        phoneSourceButton?.isEnabled =
            !running && selected != AudioMonitorService.INPUT_SOURCE_PHONE
        bluetoothSourceButton?.isEnabled =
            !running && selected != AudioMonitorService.INPUT_SOURCE_BLUETOOTH

        sourceStatusText?.text =
            when (selected) {
                AudioMonitorService.INPUT_SOURCE_BLUETOOTH ->
                    if (hasBluetoothPermission()) {
                        "BLUETOOTH HEADSET MIC selected"
                    } else {
                        "BLUETOOTH selected • Nearby devices permission required"
                    }
                else -> "PHONE MICROPHONE selected"
            }
    }

    private fun hasMicrophonePermission(): Boolean =
        checkSelfPermission(Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED

    private fun maybeRequestMicrophonePermissionOnce() {
        if (hasMicrophonePermission()) return

        val alreadyPrompted =
            prefs.getBoolean(KEY_MICROPHONE_PROMPTED, false)

        if (alreadyPrompted) return

        prefs.edit()
            .putBoolean(KEY_MICROPHONE_PROMPTED, true)
            .apply()

        requestPermissions(
            arrayOf(Manifest.permission.RECORD_AUDIO),
            REQUEST_MICROPHONE
        )
    }

    private fun openAppPermissionSettings() {
        startActivity(
            Intent(
                Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                Uri.parse("package:$packageName")
            )
        )
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

    private fun startMonitor() {
        if (!hasMicrophonePermission()) {
            Toast.makeText(
                this,
                "Microphone permission is required. " +
                    "Enable it in App permissions.",
                Toast.LENGTH_LONG
            ).show()

            openAppPermissionSettings()
            return
        }

        startForegroundService(
            Intent(this, AudioMonitorService::class.java)
                .setAction(AudioMonitorService.ACTION_START)
                .putExtra(
                    AudioMonitorService.EXTRA_INPUT_SOURCE,
                    selectedInputSource()
                )
        )

        bindAudioService()
    }

    private fun stopMonitor() {
        startService(
            Intent(this, AudioMonitorService::class.java)
                .setAction(AudioMonitorService.ACTION_STOP)
        )
    }

    private fun goLive() {
        if (!hasMicrophonePermission()) {
            openAppPermissionSettings()
            return
        }

        val publishUrl =
            gatewayEdit?.text?.toString()?.trim().orEmpty()
        val token =
            tokenEdit?.text?.toString().orEmpty()

        if (!publishUrl.startsWith("wss://")) {
            Toast.makeText(
                this,
                "Use a secure wss:// BCI Broadcast Gateway URL.",
                Toast.LENGTH_LONG
            ).show()
            return
        }

        if (token.isBlank()) {
            Toast.makeText(
                this,
                "Enter the publisher token.",
                Toast.LENGTH_LONG
            ).show()
            return
        }

        if (!isNetworkAvailable()) {
            Toast.makeText(
                this,
                "No active network connection.",
                Toast.LENGTH_LONG
            ).show()
            return
        }

        prefs.edit()
            .putString(KEY_GATEWAY_URL, publishUrl)
            .apply()

        startForegroundService(
            Intent(this, AudioMonitorService::class.java)
                .setAction(AudioMonitorService.ACTION_GO_LIVE)
                .putExtra(
                    AudioMonitorService.EXTRA_PUBLISH_URL,
                    publishUrl
                )
                .putExtra(
                    AudioMonitorService.EXTRA_PUBLISHER_TOKEN,
                    token
                )
        )

        tokenEdit?.text?.clear()
        bindAudioService()
    }

    private fun stopLive() {
        startService(
            Intent(this, AudioMonitorService::class.java)
                .setAction(AudioMonitorService.ACTION_STOP_LIVE)
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
            setPadding(
                dp(20),
                dp(16),
                dp(20),
                dp(12)
            )
            setBackgroundColor(bg)
        }

        header.addView(
            TextView(this).apply {
                text = "BCIWhisper"
                textSize = 28f
                setTextColor(cyan)
                typeface = brandTypeface
            }
        )

        header.addView(
            TextView(this).apply {
                text = "BEACON COMPUTING INITIATIVE"
                textSize = 11f
                setTextColor(primaryText)
                typeface = brandTypeface
                letterSpacing = 0.05f
            }
        )

        header.addView(
            TextView(this).apply {
                text = "ANDROID • v6.0 • ALPHA 6"
                textSize = 10f
                setTextColor(muted)
                typeface = uiTypeface
                setPadding(0, dp(2), 0, 0)
            }
        )

        root.addView(header)

        val tabs = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(dp(12), 0, dp(12), dp(10))
            setBackgroundColor(bg)
        }

        monitorTab = tabButton("MONITOR", Screen.MONITOR)
        recordingsTab =
            tabButton("RECORDINGS", Screen.RECORDINGS)
        transcriptsTab =
            tabButton("TRANSCRIPTS", Screen.TRANSCRIPTS)
        masteringTab =
            tabButton("MASTERING", Screen.MASTERING)

        listOf(
            monitorTab,
            recordingsTab,
            transcriptsTab,
            masteringTab
        ).forEach {
            tabs.addView(
                it,
                LinearLayout.LayoutParams(
                    0,
                    dp(44),
                    1f
                ).apply {
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

    private fun tabButton(
        label: String,
        screen: Screen
    ) = Button(this).apply {
        text = label
        textSize = 9.5f
        isAllCaps = false
        setTextColor(primaryText)
        typeface = uiTypeface
        setBackgroundColor(panel)
        setPadding(dp(2), 0, dp(2), 0)
        setOnClickListener {
            showScreen(screen)
        }
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
            button.setTextColor(
                if (target == screen) cyan else muted
            )
            button.setBackgroundColor(
                if (target == screen) {
                    Color.rgb(22, 42, 48)
                } else {
                    panel
                }
            )
        }

        val view = when (screen) {
            Screen.MONITOR ->
                buildMonitorScreen()

            Screen.RECORDINGS ->
                buildRecordingsScreen()

            Screen.TRANSCRIPTS ->
                buildTranscriptsScreen()

            Screen.MASTERING ->
                buildMasteringScreen()
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
        permissionText = null
        levelText = null
        baselineText = null
        baselineBar = null
        levelBar = null
        detectionText = null
        phoneSourceButton = null
        bluetoothSourceButton = null
        sourceStatusText = null
        startButton = null
        stopButton = null
        networkText = null
        gatewayEdit = null
        tokenEdit = null
        broadcastStatusText = null
        goLiveButton = null
        stopLiveButton = null

        val scroll = ScrollView(this).apply {
            isFillViewport = true
            setBackgroundColor(bg)
        }

        val body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(
                dp(18),
                dp(8),
                dp(18),
                dp(30)
            )
        }

        body.addView(sectionLabel("MICROPHONE"))

        val statusCard = card()

        stateText = textView(
            "Boundary stopped",
            16f,
            primaryText,
            role = FontRole.UI,
            bold = true
        )
        statusCard.addView(stateText)

        permissionText = textView(
            "Microphone access is used only for local audio " +
                "analysis while monitoring is active.",
            12f,
            muted
        ).apply {
            setPadding(0, dp(8), 0, 0)
        }
        statusCard.addView(permissionText)

        body.addView(statusCard)

        body.addView(
            sectionLabel("AUDIO SOURCE").apply {
                setPadding(0, dp(20), 0, dp(8))
            }
        )

        val sourceCard = card()
        sourceStatusText = textView(
            "PHONE MICROPHONE selected",
            13f,
            primaryText,
            role = FontRole.DATA
        )
        sourceCard.addView(sourceStatusText)
        sourceCard.addView(
            textView(
                "Bluetooth source uses the microphone in a paired headset or earbuds through the HFP/SCO communication path. No Bluetooth scanning or location access is used.",
                11f,
                muted
            ).apply { setPadding(0, dp(8), 0, 0) }
        )

        val sourceControls = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(12), 0, 0)
        }

        phoneSourceButton = Button(this).apply {
            text = "PHONE MIC"
            typeface = uiTypeface
            setTextColor(primaryText)
            setBackgroundColor(panel)
            setOnClickListener {
                selectInputSource(AudioMonitorService.INPUT_SOURCE_PHONE)
            }
        }

        bluetoothSourceButton = Button(this).apply {
            text = "BLUETOOTH MIC"
            typeface = uiTypeface
            setTextColor(primaryText)
            setBackgroundColor(maroon)
            setOnClickListener { requestBluetoothSource() }
        }

        sourceControls.addView(
            phoneSourceButton,
            LinearLayout.LayoutParams(0, dp(48), 1f).apply {
                setMargins(0, 0, dp(6), 0)
            }
        )
        sourceControls.addView(
            bluetoothSourceButton,
            LinearLayout.LayoutParams(0, dp(48), 1f).apply {
                setMargins(dp(6), 0, 0, 0)
            }
        )
        sourceCard.addView(sourceControls)
        body.addView(sourceCard)
        renderInputSourceControls()

        body.addView(
            sectionLabel("LIVE LEVEL").apply {
                setPadding(0, dp(20), 0, dp(8))
            }
        )

        val signalCard = card()

        levelText = textView(
            "RMS -120.0 dBFS   •   PEAK -120.0 dBFS",
            15f,
            primaryText,
            role = FontRole.DATA
        )
        signalCard.addView(levelText)

        levelBar = ProgressBar(
            this,
            null,
            android.R.attr.progressBarStyleHorizontal
        ).apply {
            max = 600
            progress = 0
        }

        signalCard.addView(
            levelBar,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(18)
            ).apply {
                setMargins(0, dp(10), 0, 0)
            }
        )

        body.addView(signalCard)

        body.addView(
            sectionLabel("ROOM BASELINE").apply {
                setPadding(0, dp(20), 0, dp(8))
            }
        )

        val baselineCard = card()

        baselineText = textView(
            "Baseline 0.0 / 60.0 s",
            15f,
            primaryText,
            role = FontRole.DATA
        )
        baselineCard.addView(baselineText)

        baselineBar = ProgressBar(
            this,
            null,
            android.R.attr.progressBarStyleHorizontal
        ).apply {
            max = 600
            progress = 0
        }

        baselineCard.addView(
            baselineBar,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(18)
            ).apply {
                setMargins(0, dp(10), 0, dp(8))
            }
        )

        baselineCard.addView(
            textView(
                "The 60-second baseline runs without blocking " +
                    "the interface.",
                12f,
                muted
            )
        )

        body.addView(baselineCard)

        body.addView(
            sectionLabel("DETECTION").apply {
                setPadding(0, dp(20), 0, dp(8))
            }
        )

        val detectionCard = card()
        detectionText = textView(
            "Waiting for baseline…",
            13f,
            primaryText,
            role = FontRole.DATA
        )
        detectionCard.addView(detectionText)
        detectionCard.addView(
            textView(
                "Two consecutive threshold crossings acquire the event. " +
                    "Once recording starts, the 5-second release grace follows " +
                    "signal continuity. Only events with at least 15 seconds " +
                    "of confirmed signal are retained.",
                11f,
                muted
            ).apply {
                setPadding(0, dp(8), 0, 0)
            }
        )
        body.addView(detectionCard)

        val controls = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            setPadding(
                0,
                dp(22),
                0,
                dp(6)
            )
        }

        startButton = Button(this).apply {
            text = "START MONITOR"
            setTextColor(Color.WHITE)
            typeface = uiTypeface
            setBackgroundColor(maroon)
            setOnClickListener {
                startMonitor()
            }
        }

        stopButton = Button(this).apply {
            text = "STOP"
            setTextColor(primaryText)
            typeface = uiTypeface
            setBackgroundColor(panel)
            isEnabled = false
            setOnClickListener {
                stopMonitor()
            }
        }

        controls.addView(
            startButton,
            LinearLayout.LayoutParams(
                0,
                dp(52),
                2f
            ).apply {
                setMargins(0, 0, dp(6), 0)
            }
        )

        controls.addView(
            stopButton,
            LinearLayout.LayoutParams(
                0,
                dp(52),
                1f
            ).apply {
                setMargins(dp(6), 0, 0, 0)
            }
        )

        body.addView(controls)

        body.addView(
            sectionLabel("BROADCAST").apply {
                setPadding(0, dp(22), 0, dp(8))
            }
        )

        val broadcastCard = card()

        networkText = textView(
            networkSummary(),
            12f,
            muted
        )
        broadcastCard.addView(networkText)

        broadcastStatusText = textView(
            "OFFLINE",
            14f,
            primaryText,
            role = FontRole.DATA
        ).apply {
            setPadding(0, dp(8), 0, dp(10))
        }
        broadcastCard.addView(broadcastStatusText)

        broadcastCard.addView(
            textView(
                "Gateway",
                11f,
                maroon,
                role = FontRole.BRAND
            )
        )

        gatewayEdit = EditText(this).apply {
            setText(
                prefs.getString(
                    KEY_GATEWAY_URL,
                    ""
                ).orEmpty()
            )
            hint =
                "wss://gateway.example/api/v1/publish/bciwhisper-main"
            setHintTextColor(muted)
            setTextColor(primaryText)
            typeface = dataTypeface
            setSingleLine(true)
            inputType =
                InputType.TYPE_CLASS_TEXT or
                    InputType.TYPE_TEXT_VARIATION_URI
            setPadding(
                dp(8),
                dp(8),
                dp(8),
                dp(8)
            )
        }
        broadcastCard.addView(gatewayEdit)

        broadcastCard.addView(
            textView(
                "Publisher token",
                11f,
                maroon,
                role = FontRole.BRAND
            ).apply {
                setPadding(0, dp(12), 0, 0)
            }
        )

        tokenEdit = EditText(this).apply {
            hint = "Token is used for this connection only"
            setHintTextColor(muted)
            setTextColor(primaryText)
            typeface = dataTypeface
            setSingleLine(true)
            inputType =
                InputType.TYPE_CLASS_TEXT or
                    InputType.TYPE_TEXT_VARIATION_PASSWORD
            setPadding(
                dp(8),
                dp(8),
                dp(8),
                dp(8)
            )
        }
        broadcastCard.addView(tokenEdit)

        val broadcastControls =
            LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                setPadding(0, dp(14), 0, 0)
            }

        goLiveButton = Button(this).apply {
            text = "GO LIVE"
            setTextColor(Color.WHITE)
            typeface = uiTypeface
            setBackgroundColor(maroon)
            setOnClickListener {
                goLive()
            }
        }

        stopLiveButton = Button(this).apply {
            text = "STOP LIVE"
            setTextColor(primaryText)
            typeface = uiTypeface
            setBackgroundColor(panel)
            isEnabled = false
            setOnClickListener {
                stopLive()
            }
        }

        broadcastControls.addView(
            goLiveButton,
            LinearLayout.LayoutParams(
                0,
                dp(50),
                1f
            ).apply {
                setMargins(0, 0, dp(6), 0)
            }
        )

        broadcastControls.addView(
            stopLiveButton,
            LinearLayout.LayoutParams(
                0,
                dp(50),
                1f
            ).apply {
                setMargins(dp(6), 0, 0, 0)
            }
        )

        broadcastCard.addView(broadcastControls)

        broadcastCard.addView(
            textView(
                "Mobile data works because the phone publishes " +
                    "outbound to a public WSS gateway. No inbound " +
                    "port or carrier port-forwarding is required. " +
                    "The current mobile uplink is PCM16 mono at " +
                    "about 0.71 Mbit/s before gateway MP3 transcode.",
                11f,
                muted
            ).apply {
                setPadding(0, dp(12), 0, 0)
            }
        )

        body.addView(broadcastCard)

        body.addView(
            sectionLabel("ANDROID PORT STATUS").apply {
                setPadding(0, dp(22), 0, dp(8))
            }
        )

        val portCard = card()

        portCard.addView(
            textView(
                "✓ Native AudioRecord hardware boundary\n" +
                    "✓ Foreground microphone service\n" +
                    "✓ One-time microphone permission request\n" +
                    "✓ Secure outbound WSS broadcast publisher\n" +
                    "✓ Cellular/Wi-Fi network awareness\n" +
                    "✓ 44.1 kHz mono PCM16 capture\n" +
                    "✓ Bounded 15-second circular ring\n" +
                    "✓ Live RMS / peak telemetry\n" +
                    "✓ 60-second baseline clock\n" +
                    "✓ Baseline-relative detector and lock lifecycle\n" +
                    "✓ 5-second release grace\n" +
                    "✓ 15-second retained-event rule\n" +
                    "✓ Raw + isolated WAV event recording\n" +
                    "✓ App-private recording library\n" +
                    "○ Adaptive spectral lock parity pending\n" +
                    "○ Reconstruction / mastering pending\n" +
                    "○ Manual transcription pending",
                13f,
                primaryText
            )
        )

        body.addView(portCard)

        body.addView(
            textView(
                "Observe accurately. Preserve faithfully. " +
                    "Analyze transparently. Communicate securely. " +
                    "Act deliberately.",
                11f,
                muted
            ).apply {
                setPadding(0, dp(28), 0, 0)
            }
        )

        body.addView(
            textView(
                "CJB-DEV-2026",
                10f,
                maroon,
                role = FontRole.DATA
            ).apply {
                setPadding(0, dp(8), 0, 0)
            }
        )

        scroll.addView(body)
        return scroll
    }

    private fun buildRecordingsScreen(): ScrollView {
        val scroll = ScrollView(this).apply {
            setBackgroundColor(bg)
        }

        val body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(14), dp(18), dp(30))
        }

        body.addView(sectionLabel("RECORDINGS"))

        val entries = audioService?.recordings().orEmpty()

        val summary = card()
        summary.addView(
            textView(
                if (entries.isEmpty()) {
                    "No retained recordings yet."
                } else {
                    "${entries.size} retained event(s)"
                },
                16f,
                primaryText,
                bold = true
            )
        )
        summary.addView(
            textView(
                "Events shorter than 15 seconds of confirmed signal are " +
                    "discarded automatically. Saved events preserve both raw " +
                    "capture and a non-destructive mobile isolated derivative.",
                11f,
                muted
            ).apply {
                setPadding(0, dp(8), 0, 0)
            }
        )

        val refresh = Button(this).apply {
            text = "REFRESH"
            typeface = uiTypeface
            setTextColor(primaryText)
            setBackgroundColor(panel)
            setOnClickListener {
                showScreen(Screen.RECORDINGS)
            }
        }
        summary.addView(
            refresh,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(46)
            ).apply {
                setMargins(0, dp(12), 0, 0)
            }
        )
        body.addView(summary)

        entries.forEach { entry ->
            val eventCard = card().apply {
                setPadding(dp(14), dp(14), dp(14), dp(14))
            }

            eventCard.addView(
                textView(
                    entry.baseName,
                    13f,
                    cyan,
                    role = FontRole.DATA
                )
            )

            val mb = entry.totalBytes / (1024.0 * 1024.0)
            eventCard.addView(
                textView(
                    String.format(
                        Locale.US,
                        "RAW %s  •  ISOLATED %s  •  %.2f MB",
                        if (entry.rawFile != null) "✓" else "—",
                        if (entry.isolatedFile != null) "✓" else "—",
                        mb
                    ),
                    11f,
                    muted,
                    role = FontRole.DATA
                ).apply {
                    setPadding(0, dp(6), 0, 0)
                }
            )

            entry.isolatedFile?.let { isolated ->
                val master = Button(this).apply {
                    text = "RECONSTRUCT + MASTER"
                    typeface = uiTypeface
                    setTextColor(primaryText)
                    setBackgroundColor(panel)
                    isEnabled = !masteringBusy
                    setOnClickListener {
                        startMastering(isolated)
                    }
                }
                eventCard.addView(
                    master,
                    LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        dp(46)
                    ).apply {
                        setMargins(0, dp(12), 0, 0)
                    }
                )

                val transcribe = Button(this).apply {
                    text = "TRANSCRIBE ISOLATED"
                    typeface = uiTypeface
                    setTextColor(Color.WHITE)
                    setBackgroundColor(maroon)
                    isEnabled = !transcriptionBusy
                    setOnClickListener {
                        startTranscription(isolated)
                    }
                }
                eventCard.addView(
                    transcribe,
                    LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        dp(46)
                    ).apply {
                        setMargins(0, dp(12), 0, 0)
                    }
                )
            }

            body.addView(
                eventCard,
                LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
                ).apply {
                    setMargins(0, dp(10), 0, 0)
                }
            )
        }

        scroll.addView(body)
        return scroll
    }

    private fun startMastering(source: java.io.File) {
        if (masteringBusy) return
        masteringBusy = true

        Toast.makeText(
            this,
            "Reconstructing and mastering locally…",
            Toast.LENGTH_SHORT
        ).show()

        Thread({
            val result = runCatching {
                masteringEngine.process(source)
            }

            runOnUiThread {
                masteringBusy = false

                result.onSuccess {
                    Toast.makeText(
                        this,
                        String.format(
                            Locale.US,
                            "Mastered • RMS %.1f dBFS • peak %.1f dBFS",
                            it.outputRmsDbfs,
                            it.outputPeakDbfs
                        ),
                        Toast.LENGTH_LONG
                    ).show()

                    showScreen(Screen.MASTERING)
                }.onFailure {
                    Toast.makeText(
                        this,
                        "Mastering failed: ${it.message}",
                        Toast.LENGTH_LONG
                    ).show()
                }
            }
        }, "BCI-MobileMastering").start()
    }

    private fun buildMasteringScreen(): ScrollView {
        val scroll = ScrollView(this).apply {
            setBackgroundColor(bg)
        }

        val body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(14), dp(18), dp(30))
        }

        body.addView(sectionLabel("MASTERING"))

        val directory =
            audioService?.recordings()
                ?.firstOrNull()
                ?.rawFile
                ?.parentFile

        val mastered =
            directory
                ?.listFiles { file ->
                    file.isFile &&
                        file.name.endsWith("_mastered.wav")
                }
                ?.sortedByDescending { it.lastModified() }
                .orEmpty()

        val summary = card()
        summary.addView(
            textView(
                if (masteringBusy) {
                    "Reconstruction / mastering is running…"
                } else if (mastered.isEmpty()) {
                    "No mastered derivatives yet."
                } else {
                    "${mastered.size} mastered derivative(s)"
                },
                16f,
                primaryText,
                bold = true
            )
        )

        summary.addView(
            textView(
                "Mobile reconstruction uses 2048-point STFT/Wiener suppression " +
                    "with harmonic protection. Mastering applies conservative " +
                    "clarity EQ, gain control, and a -1 dBFS ceiling. Original " +
                    "raw and isolated recordings are never overwritten.",
                11f,
                muted
            ).apply {
                setPadding(0, dp(8), 0, 0)
            }
        )

        summary.addView(
            textView(
                "The desktop -14 LUFS / true-peak target is not claimed here yet. " +
                    "Alpha 6 uses deterministic RMS normalization as a mobile " +
                    "pre-release stage until EBU R128 and oversampled true-peak " +
                    "validation are completed.",
                11f,
                maroon
            ).apply {
                setPadding(0, dp(10), 0, 0)
            }
        )

        body.addView(summary)

        mastered.forEach { file ->
            val c = card()
            c.addView(
                textView(
                    file.name,
                    12f,
                    cyan,
                    role = FontRole.DATA
                )
            )
            c.addView(
                textView(
                    String.format(
                        Locale.US,
                        "%.2f MB",
                        file.length() / (1024.0 * 1024.0)
                    ),
                    11f,
                    muted,
                    role = FontRole.DATA
                ).apply {
                    setPadding(0, dp(6), 0, 0)
                }
            )
            body.addView(
                c,
                LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
                ).apply {
                    setMargins(0, dp(10), 0, 0)
                }
            )
        }

        scroll.addView(body)
        return scroll
    }

    private fun startTranscription(source: java.io.File) {
        if (transcriptionBusy) return
        transcriptionBusy = true
        Toast.makeText(
            this,
            "Transcribing locally with whisper.cpp…",
            Toast.LENGTH_SHORT
        ).show()

        Thread({
            val result = runCatching {
                transcriptionEngine.transcribe(source)
            }
            runOnUiThread {
                transcriptionBusy = false
                result.onSuccess {
                    Toast.makeText(
                        this,
                        "Transcript saved: ${it.transcript.name}",
                        Toast.LENGTH_LONG
                    ).show()
                    showScreen(Screen.TRANSCRIPTS)
                }.onFailure {
                    Toast.makeText(
                        this,
                        "Transcription failed: ${it.message}",
                        Toast.LENGTH_LONG
                    ).show()
                }
            }
        }, "BCI-WhisperCpp").start()
    }

    private fun buildTranscriptsScreen(): ScrollView {
        val scroll = ScrollView(this).apply {
            setBackgroundColor(bg)
        }
        val body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(14), dp(18), dp(30))
        }

        body.addView(sectionLabel("TRANSCRIPTS"))

        val files = transcriptionEngine.transcripts()
        val summary = card()
        summary.addView(
            textView(
                if (transcriptionBusy) {
                    "whisper.cpp is transcribing locally…"
                } else if (files.isEmpty()) {
                    "No transcripts yet."
                } else {
                    "${files.size} transcript(s)"
                },
                16f,
                primaryText,
                bold = true
            )
        )
        summary.addView(
            textView(
                "Offline transcription uses whisper.cpp with the bundled tiny.en model. " +
                    "Transcription is manual and never runs in the capture thread.",
                11f,
                muted
            ).apply {
                setPadding(0, dp(8), 0, 0)
            }
        )
        body.addView(summary)

        files.forEach { file ->
            val c = card().apply {
                setPadding(dp(14), dp(14), dp(14), dp(14))
            }
            c.addView(
                textView(
                    file.name,
                    12f,
                    cyan,
                    role = FontRole.DATA
                )
            )
            c.addView(
                textView(
                    runCatching { file.readText().trim() }
                        .getOrElse { "Unable to read transcript" }
                        .ifBlank { "(empty transcript)" },
                    14f,
                    primaryText
                ).apply {
                    setPadding(0, dp(8), 0, 0)
                }
            )
            body.addView(
                c,
                LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
                ).apply {
                    setMargins(0, dp(10), 0, 0)
                }
            )
        }

        scroll.addView(body)
        return scroll
    }

    private fun buildPendingScreen(
        title: String,
        bodyText: String,
        note: String
    ): ScrollView {
        val scroll = ScrollView(this).apply {
            setBackgroundColor(bg)
        }

        val body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(
                dp(18),
                dp(14),
                dp(18),
                dp(30)
            )
        }

        body.addView(sectionLabel(title))

        val c = card()

        c.addView(
            textView(
                bodyText,
                16f,
                primaryText
            )
        )

        c.addView(
            textView(
                note,
                12f,
                muted
            ).apply {
                setPadding(0, dp(16), 0, 0)
            }
        )

        body.addView(c)

        body.addView(
            textView(
                "This screen is intentionally present before " +
                    "the subsystem is enabled so the mobile " +
                    "workflow remains stable while functionality " +
                    "is ported behind it.",
                12f,
                muted
            ).apply {
                setPadding(0, dp(20), 0, 0)
            }
        )

        scroll.addView(body)
        return scroll
    }

    private fun card() =
        LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(
                dp(16),
                dp(16),
                dp(16),
                dp(16)
            )
            setBackgroundColor(panel)
        }

    private fun sectionLabel(
        label: String
    ) = TextView(this).apply {
        text = label
        textSize = 12f
        setTextColor(maroon)
        typeface = brandTypeface
        letterSpacing = 0.08f
        setPadding(0, dp(8), 0, dp(8))
    }

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
            FontRole.BRAND ->
                brandTypeface

            FontRole.UI ->
                if (bold) {
                    Typeface.create(
                        uiTypeface,
                        Typeface.BOLD
                    )
                } else {
                    uiTypeface
                }

            FontRole.DATA ->
                dataTypeface
        }

        setLineSpacing(0f, 1.12f)
    }

    private fun renderSnapshot() {
        if (currentScreen != Screen.MONITOR) return

        networkText?.text = networkSummary()

        val hasPermission =
            hasMicrophonePermission()
        val snapshot =
            audioService?.snapshot()

        permissionText?.text =
            if (hasPermission) {
                "Microphone permission enabled • capture occurs " +
                    "only while monitoring is active."
            } else {
                "Microphone permission is off. BCIWhisper will " +
                    "not prompt again automatically; use Start " +
                    "Monitor to open App permissions."
            }

        if (snapshot == null) {
            stateText?.text = when {
                !hasPermission ->
                    "MICROPHONE PERMISSION REQUIRED"

                bound ->
                    "Microphone boundary ready"

                else ->
                    "Boundary stopped"
            }

            startButton?.text =
                if (hasPermission) {
                    "START MONITOR"
                } else {
                    "OPEN PERMISSIONS"
                }

            startButton?.isEnabled = true
            stopButton?.isEnabled = false

            broadcastStatusText?.text = "OFFLINE"
            goLiveButton?.isEnabled =
                hasPermission && isNetworkAvailable()
            stopLiveButton?.isEnabled = false
            return
        }

        stateText?.text = when {
            snapshot.lastError != null ->
                "ERROR • ${snapshot.lastError}"

            !hasPermission ->
                "MICROPHONE PERMISSION REQUIRED"

            snapshot.recordingActive ->
                "SIGNAL LOCKED • RECORDING"

            snapshot.running &&
                !snapshot.baselineComplete ->
                "CALIBRATING • ${snapshot.sampleRate} Hz"

            snapshot.running ->
                "MONITORING • " + snapshot.inputDevice + " • " + snapshot.sampleRate + " Hz"

            else ->
                "Boundary stopped"
        }

        levelText?.text = String.format(
            Locale.US,
            "RMS %.1f dBFS   •   PEAK %.1f dBFS",
            snapshot.rmsDbfs,
            snapshot.peakDbfs
        )

        detectionText?.text =
            when {
                !snapshot.baselineComplete ->
                    String.format(
                        Locale.US,
                        "BASELINING • %.1f / 60.0 s",
                        snapshot.baselineSeconds
                    )

                snapshot.recordingActive ->
                    String.format(
                        Locale.US,
                        "SIGNAL LOCKED • SNR %.1f dB • %.1f s confirmed",
                        snapshot.snrDb,
                        snapshot.lockedSeconds
                    )

                snapshot.signalActive ->
                    String.format(
                        Locale.US,
                        "TRIGGER ACTIVE • SNR %.1f dB • floor %.1f dBFS",
                        snapshot.snrDb,
                        snapshot.noiseFloorDbfs
                    )

                snapshot.lastEventSummary != null ->
                    snapshot.lastEventSummary

                else ->
                    String.format(
                        Locale.US,
                        "MONITORING • SNR %.1f dB • floor %.1f dBFS",
                        snapshot.snrDb,
                        snapshot.noiseFloorDbfs
                    )
            }

        val peakForMeter =
            snapshot.peakDbfs.coerceIn(-60.0, 0.0)

        levelBar?.progress =
            ((peakForMeter + 60.0) * 10.0)
                .toInt()
                .coerceIn(0, 600)

        baselineText?.text =
            if (snapshot.baselineComplete) {
                "Baseline complete • 60.0 s"
            } else {
                String.format(
                    Locale.US,
                    "Baseline %.1f / 60.0 s",
                    snapshot.baselineSeconds
                )
            }

        baselineBar?.progress =
            (snapshot.baselineSeconds * 10.0)
                .toInt()
                .coerceIn(0, 600)

        startButton?.text =
            if (hasPermission) {
                "START MONITOR"
            } else {
                "OPEN PERMISSIONS"
            }

        startButton?.isEnabled = !snapshot.running
        stopButton?.isEnabled = snapshot.running

        renderInputSourceControls()
        if (snapshot.running) {
            sourceStatusText?.text = "ACTIVE • " + snapshot.inputDevice
        }

        val broadcastStatus =
            when (snapshot.broadcastState) {
                BroadcastPublisher.State.LIVE ->
                    String.format(
                        Locale.US,
                        "LIVE • %.2f MB sent • %d dropped",
                        snapshot.broadcastBytesSent /
                            (1024.0 * 1024.0),
                        snapshot.broadcastDroppedFrames
                    )

                BroadcastPublisher.State.CONNECTING ->
                    "CONNECTING"

                BroadcastPublisher.State.RETRYING ->
                    "RECONNECTING • " +
                        (
                            snapshot.broadcastLastError
                                ?: "network transition"
                        )

                BroadcastPublisher.State.ERROR ->
                    "ERROR • " +
                        (
                            snapshot.broadcastLastError
                                ?: "publisher error"
                        )

                BroadcastPublisher.State.OFFLINE ->
                    "OFFLINE"
            }

        broadcastStatusText?.text =
            broadcastStatus

        val liveOrConnecting =
            snapshot.broadcastState !=
                BroadcastPublisher.State.OFFLINE &&
                snapshot.broadcastState !=
                BroadcastPublisher.State.ERROR

        goLiveButton?.isEnabled =
            hasPermission &&
                isNetworkAvailable() &&
                !liveOrConnecting

        stopLiveButton?.isEnabled =
            liveOrConnecting
    }

    private fun isNetworkAvailable(): Boolean {
        val manager =
            getSystemService(
                ConnectivityManager::class.java
            )

        val network =
            manager.activeNetwork
                ?: return false

        val capabilities =
            manager.getNetworkCapabilities(network)
                ?: return false

        return capabilities.hasCapability(
            NetworkCapabilities.NET_CAPABILITY_INTERNET
        )
    }

    private fun networkSummary(): String {
        val manager =
            getSystemService(
                ConnectivityManager::class.java
            )

        val network =
            manager.activeNetwork
                ?: return "NETWORK • OFFLINE"

        val capabilities =
            manager.getNetworkCapabilities(network)
                ?: return "NETWORK • OFFLINE"

        return when {
            capabilities.hasTransport(
                NetworkCapabilities.TRANSPORT_CELLULAR
            ) ->
                "CELLULAR • outbound WSS supported • mobile data will be used"

            capabilities.hasTransport(
                NetworkCapabilities.TRANSPORT_WIFI
            ) ->
                "WI-FI • outbound WSS supported"

            capabilities.hasTransport(
                NetworkCapabilities.TRANSPORT_ETHERNET
            ) ->
                "ETHERNET • outbound WSS supported"

            capabilities.hasTransport(
                NetworkCapabilities.TRANSPORT_VPN
            ) ->
                "VPN • outbound WSS supported"

            else ->
                "NETWORK • outbound WSS supported"
        }
    }

    private fun dp(value: Int): Int =
        (
            value *
                resources.displayMetrics.density
        ).toInt()

    companion object {
        private const val REQUEST_MICROPHONE = 100
        private const val REQUEST_BLUETOOTH_CONNECT = 101
        private const val PREFS_NAME =
            "bciwhisper_permissions"
        private const val KEY_MICROPHONE_PROMPTED =
            "microphone_prompted_once"
        private const val KEY_GATEWAY_URL =
            "broadcast_gateway_url"
        private const val KEY_BLUETOOTH_PROMPTED =
            "bluetooth_connect_prompted_once"
        private const val KEY_INPUT_SOURCE =
            "input_source"
    }
}
