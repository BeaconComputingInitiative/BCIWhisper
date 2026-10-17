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
import kotlin.math.log10
import kotlin.math.sqrt

class AudioMonitorService : Service() {
    inner class LocalBinder : Binder() {
        fun service(): AudioMonitorService = this@AudioMonitorService
    }

    data class Snapshot(
        val running: Boolean,
        val sampleRate: Int,
        val rmsDbfs: Double,
        val peakDbfs: Double,
        val baselineSeconds: Double,
        val baselineComplete: Boolean,
        val framesCaptured: Long,
        val lastError: String?,
        val broadcastState: BroadcastPublisher.State,
        val broadcastBytesSent: Long,
        val broadcastDroppedFrames: Long,
        val broadcastLastError: String?
    )

    private val binder = LocalBinder()
    private val ring = AudioRingBuffer(44100 * 15)
    private val publisher = BroadcastPublisher()

    @Volatile private var running = false
    @Volatile private var rmsDbfs = -120.0
    @Volatile private var peakDbfs = -120.0
    @Volatile private var baselineSeconds = 0.0
    @Volatile private var baselineComplete = false
    @Volatile private var framesCaptured = 0L
    @Volatile private var lastError: String? = null

    private var audioRecord: AudioRecord? = null
    private var worker: Thread? = null
    private var lastNotificationState: BroadcastPublisher.State? = null

    override fun onBind(intent: Intent?): IBinder = binder

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startMonitoring()
            ACTION_STOP -> stopMonitoring()
            ACTION_GO_LIVE -> {
                startMonitoring()
                val url = intent.getStringExtra(EXTRA_PUBLISH_URL).orEmpty().trim()
                val token = intent.getStringExtra(EXTRA_PUBLISHER_TOKEN).orEmpty()
                try {
                    publisher.start(url, token)
                    updateNotification(force = true)
                } catch (t: Throwable) {
                    lastError = "Go Live: ${t.message ?: t::class.simpleName}"
                }
            }
            ACTION_STOP_LIVE -> {
                publisher.stop()
                updateNotification(force = true)
            }
        }
        return START_NOT_STICKY
    }

    fun snapshot(): Snapshot {
        val broadcast = publisher.snapshot()
        return Snapshot(
            running = running,
            sampleRate = SAMPLE_RATE,
            rmsDbfs = rmsDbfs,
            peakDbfs = peakDbfs,
            baselineSeconds = baselineSeconds,
            baselineComplete = baselineComplete,
            framesCaptured = framesCaptured,
            lastError = lastError,
            broadcastState = broadcast.state,
            broadcastBytesSent = broadcast.bytesSent,
            broadcastDroppedFrames = broadcast.droppedFrames,
            broadcastLastError = broadcast.lastError
        )
    }

    private fun buildRecorder(): AudioRecord {
        val minBuffer = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        )
        require(minBuffer > 0) {
            "AudioRecord.getMinBufferSize failed: $minBuffer"
        }

        val source = if (Build.VERSION.SDK_INT >= 24) {
            MediaRecorder.AudioSource.UNPROCESSED
        } else {
            MediaRecorder.AudioSource.VOICE_RECOGNITION
        }

        val format = AudioFormat.Builder()
            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
            .setSampleRate(SAMPLE_RATE)
            .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
            .build()

        return AudioRecord.Builder()
            .setAudioSource(source)
            .setAudioFormat(format)
            .setBufferSizeInBytes((minBuffer * 4).coerceAtLeast(32768))
            .build()
    }

    private fun startMonitoring() {
        if (running) return

        if (
            checkSelfPermission(Manifest.permission.RECORD_AUDIO) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            lastError = "RECORD_AUDIO permission not granted"
            stopSelf()
            return
        }

        startForeground(
            NOTIFICATION_ID,
            notification("Microphone boundary starting…")
        )

        try {
            audioRecord = buildRecorder()
            check(audioRecord?.state == AudioRecord.STATE_INITIALIZED) {
                "AudioRecord did not initialize"
            }

            ring.clear()
            framesCaptured = 0
            baselineSeconds = 0.0
            baselineComplete = false
            lastError = null

            audioRecord!!.startRecording()
            running = true

            worker = Thread(
                { captureLoop() },
                "BCI-AudioBoundary"
            ).also { it.start() }

            updateNotification(force = true)
        } catch (t: Throwable) {
            lastError = "${t::class.simpleName}: ${t.message}"
            running = false
            audioRecord?.release()
            audioRecord = null
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private fun captureLoop() {
        val block = ShortArray(2048)

        while (running) {
            val n = audioRecord?.read(
                block,
                0,
                block.size,
                AudioRecord.READ_BLOCKING
            ) ?: -1

            if (n <= 0) {
                if (running) lastError = "AudioRecord.read returned $n"
                continue
            }

            ring.write(block, n)
            publisher.submitPcm(block, n)

            framesCaptured += n
            baselineSeconds = (
                framesCaptured.toDouble() / SAMPLE_RATE
            ).coerceAtMost(BASELINE_SECONDS)
            baselineComplete = baselineSeconds >= BASELINE_SECONDS

            var sumSq = 0.0
            var peak = 0

            for (i in 0 until n) {
                val value = block[i].toInt()
                sumSq += value.toDouble() * value.toDouble()
                val absolute = kotlin.math.abs(value)
                if (absolute > peak) peak = absolute
            }

            val rms = sqrt(sumSq / n.coerceAtLeast(1))
            rmsDbfs = if (rms > 0.0) {
                20.0 * log10(rms / 32768.0)
            } else {
                -120.0
            }
            peakDbfs = if (peak > 0) {
                20.0 * log10(peak.toDouble() / 32768.0)
            } else {
                -120.0
            }

            updateNotification()
        }
    }

    private fun stopMonitoring() {
        publisher.stop()
        running = false

        try {
            audioRecord?.stop()
        } catch (_: Throwable) {
        }

        try {
            worker?.join(1200)
        } catch (_: InterruptedException) {
        }

        worker = null
        audioRecord?.release()
        audioRecord = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        publisher.stop()
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
        val channel = NotificationChannel(
            CHANNEL_ID,
            "BCIWhisper microphone",
            NotificationManager.IMPORTANCE_LOW
        )
        channel.description =
            "Foreground microphone analysis and operator-enabled live broadcast"

        getSystemService(NotificationManager::class.java)
            .createNotificationChannel(channel)
    }

    private fun updateNotification(force: Boolean = false) {
        if (!running) return

        val broadcastState = publisher.snapshot().state
        if (!force && broadcastState == lastNotificationState) return
        lastNotificationState = broadcastState

        val message = when (broadcastState) {
            BroadcastPublisher.State.LIVE ->
                "Monitoring microphone • LIVE broadcast"
            BroadcastPublisher.State.CONNECTING ->
                "Monitoring microphone • connecting broadcast"
            BroadcastPublisher.State.RETRYING ->
                "Monitoring microphone • reconnecting broadcast"
            BroadcastPublisher.State.ERROR ->
                "Monitoring microphone • broadcast error"
            BroadcastPublisher.State.OFFLINE ->
                "Microphone monitoring active"
        }

        getSystemService(NotificationManager::class.java)
            .notify(NOTIFICATION_ID, notification(message))
    }

    private fun notification(message: String): Notification {
        val pending = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_bci_notification)
            .setContentTitle("BCIWhisper")
            .setContentText(message)
            .setOngoing(true)
            .setContentIntent(pending)
            .build()
    }

    companion object {
        const val ACTION_START =
            "org.beaconcomputinginitiative.bciwhisper.START"
        const val ACTION_STOP =
            "org.beaconcomputinginitiative.bciwhisper.STOP"
        const val ACTION_GO_LIVE =
            "org.beaconcomputinginitiative.bciwhisper.GO_LIVE"
        const val ACTION_STOP_LIVE =
            "org.beaconcomputinginitiative.bciwhisper.STOP_LIVE"

        const val EXTRA_PUBLISH_URL = "publish_url"
        const val EXTRA_PUBLISHER_TOKEN = "publisher_token"

        private const val CHANNEL_ID = "bciwhisper_audio"
        private const val NOTIFICATION_ID = 5201
        private const val SAMPLE_RATE = 44100
        private const val BASELINE_SECONDS = 60.0
    }
}
