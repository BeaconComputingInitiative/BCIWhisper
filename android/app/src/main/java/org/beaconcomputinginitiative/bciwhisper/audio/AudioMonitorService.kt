package org.beaconcomputinginitiative.bciwhisper.audio

import android.Manifest
import android.app.*
import android.content.Intent
import android.content.pm.PackageManager
import android.media.*
import android.os.*
import org.beaconcomputinginitiative.bciwhisper.MainActivity
import org.beaconcomputinginitiative.bciwhisper.R
import org.beaconcomputinginitiative.bciwhisper.broadcast.BroadcastPublisher
import java.io.File
import kotlin.math.log10
import kotlin.math.sqrt

class AudioMonitorService : Service() {
    inner class LocalBinder : Binder() {
        fun service(): AudioMonitorService =
            this@AudioMonitorService
    }

    data class RecordingEntry(
        val baseName: String,
        val rawFile: File?,
        val isolatedFile: File?,
        val modified: Long,
        val totalBytes: Long
    )

    data class Snapshot(
        val running: Boolean,
        val sampleRate: Int,
        val rmsDbfs: Double,
        val peakDbfs: Double,
        val baselineSeconds: Double,
        val baselineComplete: Boolean,
        val noiseFloorDbfs: Double,
        val snrDb: Double,
        val signalActive: Boolean,
        val lockLowHz: Double,
        val lockHighHz: Double,
        val lockCenterHz: Double,
        val lockExcessDb: Double,
        val spectrumBands: FloatArray,
        val recordingActive: Boolean,
        val lockedSeconds: Double,
        val lastEventSummary: String?,
        val framesCaptured: Long,
        val inputSource: String,
        val inputDevice: String,
        val lastError: String?,
        val broadcastState: BroadcastPublisher.State,
        val broadcastBytesSent: Long,
        val broadcastDroppedFrames: Long,
        val broadcastLastError: String?
    )

    private val binder = LocalBinder()
    private val ring =
        AudioRingBuffer(SAMPLE_RATE * 15)

    private val publisher =
        BroadcastPublisher()

    private val bluetoothRouter by lazy {
        BluetoothAudioRouter(this)
    }

    @Volatile
    private var inputSource = INPUT_SOURCE_PHONE

    @Volatile
    private var inputDevice = "Phone microphone"

    private lateinit var detector:
        DetectionEngine

    private lateinit var recorder:
        EventRecorder

    @Volatile private var running = false
    @Volatile private var rmsDbfs = -120.0
    @Volatile private var peakDbfs = -120.0
    @Volatile private var baselineSeconds = 0.0
    @Volatile private var baselineComplete = false
    @Volatile private var noiseFloorDbfs = -120.0
    @Volatile private var snrDb = 0.0
    @Volatile private var signalActive = false
    @Volatile private var lockLowHz = 80.0
    @Volatile private var lockHighHz = 8500.0
    @Volatile private var lockCenterHz = 1200.0
    @Volatile private var lockExcessDb = -120.0
    @Volatile private var spectrumBands = FloatArray(40)
    @Volatile private var framesCaptured = 0L
    @Volatile private var lastError: String? = null
    @Volatile private var lastEventSummary: String? = null

    private var audioRecord: AudioRecord? = null
    private var worker: Thread? = null

    private var lastNotificationSignature: String? =
        null

    private val recordingsDirectory: File by lazy {
        File(
            getExternalFilesDir(
                Environment.DIRECTORY_MUSIC
            ) ?: filesDir,
            "BCIWhisper/Recordings"
        ).apply {
            mkdirs()
        }
    }

    override fun onCreate() {
        super.onCreate()

        detector = DetectionEngine(
            sampleRate = SAMPLE_RATE,
            blockSize = BLOCK_SIZE,
            baselineSecondsRequired =
                BASELINE_SECONDS
        )

        recorder = EventRecorder(
            directory =
                recordingsDirectory,
            sampleRate =
                SAMPLE_RATE
        )

        createNotificationChannel()
    }

    override fun onBind(
        intent: Intent?
    ): IBinder = binder

    override fun onStartCommand(
        intent: Intent?,
        flags: Int,
        startId: Int
    ): Int {
        when (intent?.action) {
            ACTION_START -> {
                inputSource = intent.getStringExtra(EXTRA_INPUT_SOURCE)
                    ?.takeIf { it == INPUT_SOURCE_PHONE || it == INPUT_SOURCE_BLUETOOTH }
                    ?: INPUT_SOURCE_PHONE
                startMonitoring()
            }

            ACTION_STOP ->
                stopMonitoring()

            ACTION_GO_LIVE -> {
                startMonitoring()

                val url =
                    intent
                        .getStringExtra(
                            EXTRA_PUBLISH_URL
                        )
                        .orEmpty()
                        .trim()

                val token =
                    intent
                        .getStringExtra(
                            EXTRA_PUBLISHER_TOKEN
                        )
                        .orEmpty()

                try {
                    publisher.start(
                        url,
                        token
                    )

                    updateNotification(
                        force = true
                    )
                } catch (t: Throwable) {
                    lastError =
                        "Go Live: " +
                            (
                                t.message
                                    ?: t::class.simpleName
                                    ?: "error"
                                )
                }
            }

            ACTION_STOP_LIVE -> {
                publisher.stop()

                updateNotification(
                    force = true
                )
            }
        }

        return START_NOT_STICKY
    }

    fun snapshot(): Snapshot {
        val broadcast =
            publisher.snapshot()

        return Snapshot(
            running = running,
            sampleRate = SAMPLE_RATE,
            rmsDbfs = rmsDbfs,
            peakDbfs = peakDbfs,
            baselineSeconds =
                baselineSeconds,
            baselineComplete =
                baselineComplete,
            noiseFloorDbfs =
                noiseFloorDbfs,
            snrDb = snrDb,
            signalActive =
                signalActive,
            lockLowHz = lockLowHz,
            lockHighHz = lockHighHz,
            lockCenterHz = lockCenterHz,
            lockExcessDb = lockExcessDb,
            spectrumBands = spectrumBands.copyOf(),
            recordingActive =
                recorder.active,
            lockedSeconds =
                recorder.lockedSeconds,
            lastEventSummary =
                lastEventSummary,
            framesCaptured =
                framesCaptured,
            inputSource = inputSource,
            inputDevice = inputDevice,
            lastError = lastError,
            broadcastState =
                broadcast.state,
            broadcastBytesSent =
                broadcast.bytesSent,
            broadcastDroppedFrames =
                broadcast.droppedFrames,
            broadcastLastError =
                broadcast.lastError
        )
    }

    fun recordings(): List<RecordingEntry> {
        val groups =
            recordingsDirectory
                .listFiles()
                .orEmpty()
                .filter {
                    it.isFile &&
                        it.extension.equals(
                            "wav",
                            ignoreCase = true
                        )
                }
                .groupBy { file ->
                    file.name
                        .removeSuffix("_raw.wav")
                        .removeSuffix(
                            "_isolated.wav"
                        )
                }

        return groups
            .map { (base, files) ->
                val raw =
                    files.firstOrNull {
                        it.name.endsWith(
                            "_raw.wav"
                        )
                    }

                val isolated =
                    files.firstOrNull {
                        it.name.endsWith(
                            "_isolated.wav"
                        )
                    }

                RecordingEntry(
                    baseName = base,
                    rawFile = raw,
                    isolatedFile =
                        isolated,
                    modified =
                        files.maxOfOrNull {
                            it.lastModified()
                        } ?: 0L,
                    totalBytes =
                        files.sumOf {
                            it.length()
                        }
                )
            }
            .sortedByDescending {
                it.modified
            }
    }

    private fun buildRecorder():
        AudioRecord {
        val minBuffer =
            AudioRecord
                .getMinBufferSize(
                    SAMPLE_RATE,
                    AudioFormat
                        .CHANNEL_IN_MONO,
                    AudioFormat
                        .ENCODING_PCM_16BIT
                )

        require(minBuffer > 0) {
            "AudioRecord.getMinBufferSize " +
                "failed: $minBuffer"
        }

        val usingBluetooth = inputSource == INPUT_SOURCE_BLUETOOTH

        val route = if (usingBluetooth) {
            bluetoothRouter.route()
        } else {
            bluetoothRouter.clear()
            BluetoothAudioRouter.RouteResult(
                routed = true,
                label = "Phone microphone",
                device = null
            )
        }

        require(route.routed) { route.label }
        inputDevice = route.label

        val source =
            if (usingBluetooth) {
                MediaRecorder.AudioSource.VOICE_COMMUNICATION
            } else if (Build.VERSION.SDK_INT >= 24) {
                MediaRecorder.AudioSource.UNPROCESSED
            } else {
                MediaRecorder.AudioSource.VOICE_RECOGNITION
            }

        val format =
            AudioFormat.Builder()
                .setEncoding(
                    AudioFormat
                        .ENCODING_PCM_16BIT
                )
                .setSampleRate(
                    SAMPLE_RATE
                )
                .setChannelMask(
                    AudioFormat
                        .CHANNEL_IN_MONO
                )
                .build()

        val built = AudioRecord.Builder()
            .setAudioSource(source)
            .setAudioFormat(format)
            .setBufferSizeInBytes(
                (minBuffer * 4)
                    .coerceAtLeast(32768)
            )
            .build()

        if (usingBluetooth && route.device != null) {
            bluetoothRouter.prefer(built, route.device)
        }

        return built
    }

    private fun startMonitoring() {
        if (running) return

        if (
            checkSelfPermission(
                Manifest.permission.RECORD_AUDIO
            ) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            lastError =
                "RECORD_AUDIO permission " +
                    "not granted"

            stopSelf()
            return
        }

        startForeground(
            NOTIFICATION_ID,
            notification(
                "Microphone boundary starting…"
            )
        )

        try {
            audioRecord =
                buildRecorder()

            check(
                audioRecord?.state ==
                    AudioRecord
                        .STATE_INITIALIZED
            ) {
                "AudioRecord did not initialize"
            }

            ring.clear()
            detector.reset()
            recorder.abort()

            framesCaptured = 0
            baselineSeconds = 0.0
            baselineComplete = false
            noiseFloorDbfs = -120.0
            snrDb = 0.0
            signalActive = false
            lockLowHz = 80.0
            lockHighHz = 8500.0
            lockCenterHz = 1200.0
            lockExcessDb = -120.0
            spectrumBands = FloatArray(40)
            lastError = null
            lastEventSummary = null

            audioRecord!!
                .startRecording()

            running = true

            worker =
                Thread(
                    {
                        captureLoop()
                    },
                    "BCI-AudioBoundary"
                ).also {
                    it.start()
                }

            updateNotification(
                force = true
            )
        } catch (t: Throwable) {
            lastError =
                "${t::class.simpleName}: " +
                    "${t.message}"

            running = false

            audioRecord?.release()
            audioRecord = null

            stopForeground(
                STOP_FOREGROUND_REMOVE
            )

            stopSelf()
        }
    }

    private fun captureLoop() {
        val block =
            ShortArray(BLOCK_SIZE)

        while (running) {
            val n =
                audioRecord?.read(
                    block,
                    0,
                    block.size,
                    AudioRecord
                        .READ_BLOCKING
                ) ?: -1

            if (n <= 0) {
                if (running) {
                    lastError =
                        "AudioRecord.read " +
                            "returned $n"
                }

                continue
            }

            ring.write(
                block,
                n
            )

            publisher.submitPcm(
                block,
                n
            )

            framesCaptured +=
                n.toLong()

            updateLevelTelemetry(
                block,
                n
            )

            val detection =
                detector.process(
                    block,
                    n
                )

            baselineSeconds =
                detection
                    .baselineSeconds

            baselineComplete =
                detection
                    .baselineComplete

            noiseFloorDbfs =
                detection
                    .noiseFloorDbfs

            snrDb =
                detection.snrDb

            signalActive =
                detection.signalActive

            lockLowHz = detection.lockLowHz
            lockHighHz = detection.lockHighHz
            lockCenterHz = detection.lockCenterHz
            lockExcessDb = detection.lockExcessDb
            spectrumBands = detection.spectrumBands

            if (
                baselineComplete &&
                detection.confirmedTrigger &&
                !recorder.active
            ) {
                val preRoll =
                    ring.snapshot(
                        SAMPLE_RATE
                    )

                recorder.start(
                    preRoll
                )
            }

            if (recorder.active) {
                recorder.append(
                    block,
                    n,
                    signalActive
                )

                if (
                    recorder
                        .shouldStopForLoss()
                ) {
                    finishRecording(
                        "signal_lost"
                    )
                }
            }

            updateNotification()
        }
    }

    private fun updateLevelTelemetry(
        block: ShortArray,
        count: Int
    ) {
        val n =
            count
                .coerceAtMost(
                    block.size
                )
                .coerceAtLeast(1)

        var sumSq = 0.0
        var peak = 0

        for (i in 0 until n) {
            val value =
                block[i].toInt()

            sumSq +=
                value.toDouble() *
                    value.toDouble()

            val absolute =
                kotlin.math.abs(
                    value
                )

            if (absolute > peak) {
                peak = absolute
            }
        }

        val rms =
            sqrt(
                sumSq /
                    n
            )

        rmsDbfs =
            if (rms > 0.0) {
                20.0 *
                    log10(
                        rms /
                            32768.0
                    )
            } else {
                -120.0
            }

        peakDbfs =
            if (peak > 0) {
                20.0 *
                    log10(
                        peak.toDouble() /
                            32768.0
                    )
            } else {
                -120.0
            }
    }

    private fun finishRecording(
        reason: String
    ) {
        val event =
            recorder.finish(
                reason
            )

        lastEventSummary =
            if (event.kept) {
                "SAVED • " +
                    String.format(
                        java.util.Locale.US,
                        "%.1fs lock / %.1fs total",
                        event.lockedSeconds,
                        event.totalSeconds
                    )
            } else {
                "DISCARDED • " +
                    String.format(
                        java.util.Locale.US,
                        "%.1fs lock < 15.0s keep rule",
                        event.lockedSeconds
                    )
            }
    }

    private fun stopMonitoring() {
        publisher.stop()
        bluetoothRouter.clear()

        if (recorder.active) {
            finishRecording(
                "operator_stop"
            )
        }

        running = false

        try {
            audioRecord?.stop()
        } catch (_: Throwable) {
        }

        try {
            worker?.join(
                1200
            )
        } catch (
            _: InterruptedException
        ) {
        }

        worker = null

        audioRecord?.release()
        audioRecord = null

        stopForeground(
            STOP_FOREGROUND_REMOVE
        )

        stopSelf()
    }

    override fun onDestroy() {
        publisher.stop()
        bluetoothRouter.clear()

        if (recorder.active) {
            recorder.abort()
        }

        running = false

        try {
            audioRecord?.stop()
        } catch (_: Throwable) {
        }

        audioRecord?.release()
        audioRecord = null

        super.onDestroy()
    }

    private fun createNotificationChannel() {
        val channel =
            NotificationChannel(
                CHANNEL_ID,
                "BCIWhisper microphone",
                NotificationManager
                    .IMPORTANCE_LOW
            )

        channel.description =
            "Foreground microphone analysis, " +
                "event recording, and " +
                "operator-enabled live broadcast"

        getSystemService(
            NotificationManager::class.java
        ).createNotificationChannel(
            channel
        )
    }

    private fun updateNotification(
        force: Boolean = false
    ) {
        if (!running) return

        val broadcastState =
            publisher.snapshot().state

        val recordingState =
            when {
                recorder.active ->
                    "recording"

                baselineComplete ->
                    "monitoring"

                else ->
                    "calibrating"
            }

        val signature =
            "${broadcastState.name}:" +
                recordingState

        if (
            !force &&
            signature ==
                lastNotificationSignature
        ) {
            return
        }

        lastNotificationSignature =
            signature

        val message =
            buildString {
                append(
                    when {
                        recorder.active ->
                            "SIGNAL LOCKED • recording"

                        !baselineComplete ->
                            "Calibrating room baseline"

                        else ->
                            "Microphone monitoring active"
                    }
                )

                when (broadcastState) {
                    BroadcastPublisher
                        .State.LIVE ->
                        append(
                            " • LIVE broadcast"
                        )

                    BroadcastPublisher
                        .State.CONNECTING ->
                        append(
                            " • connecting broadcast"
                        )

                    BroadcastPublisher
                        .State.RETRYING ->
                        append(
                            " • reconnecting broadcast"
                        )

                    BroadcastPublisher
                        .State.ERROR ->
                        append(
                            " • broadcast error"
                        )

                    BroadcastPublisher
                        .State.OFFLINE -> {
                    }
                }
            }

        getSystemService(
            NotificationManager::class.java
        ).notify(
            NOTIFICATION_ID,
            notification(
                message
            )
        )
    }

    private fun notification(
        message: String
    ): Notification {
        val pending =
            PendingIntent.getActivity(
                this,
                0,
                Intent(
                    this,
                    MainActivity::class.java
                ),
                PendingIntent.FLAG_IMMUTABLE or
                    PendingIntent
                        .FLAG_UPDATE_CURRENT
            )

        return Notification.Builder(
            this,
            CHANNEL_ID
        )
            .setSmallIcon(
                R.drawable
                    .ic_bci_notification
            )
            .setContentTitle(
                "BCIWhisper"
            )
            .setContentText(
                message
            )
            .setOngoing(true)
            .setContentIntent(
                pending
            )
            .build()
    }

    companion object {
        const val ACTION_START =
            "org.beaconcomputinginitiative." +
                "bciwhisper.START"

        const val ACTION_STOP =
            "org.beaconcomputinginitiative." +
                "bciwhisper.STOP"

        const val ACTION_GO_LIVE =
            "org.beaconcomputinginitiative." +
                "bciwhisper.GO_LIVE"

        const val ACTION_STOP_LIVE =
            "org.beaconcomputinginitiative." +
                "bciwhisper.STOP_LIVE"

        const val EXTRA_PUBLISH_URL =
            "publish_url"

        const val EXTRA_PUBLISHER_TOKEN =
            "publisher_token"

        const val EXTRA_INPUT_SOURCE =
            "input_source"

        const val INPUT_SOURCE_PHONE =
            "phone"

        const val INPUT_SOURCE_BLUETOOTH =
            "bluetooth"

        private const val CHANNEL_ID =
            "bciwhisper_audio"

        private const val NOTIFICATION_ID =
            5201

        private const val SAMPLE_RATE =
            44100

        private const val BLOCK_SIZE =
            2048

        private const val BASELINE_SECONDS =
            60.0
    }
}
