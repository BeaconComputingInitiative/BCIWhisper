package org.beaconcomputinginitiative.bciwhisper.audio

import android.Manifest
import android.app.*
import android.content.Intent
import android.content.pm.PackageManager
import android.media.*
import android.os.*
import org.beaconcomputinginitiative.bciwhisper.MainActivity
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
        val lastError: String?
    )

    private val binder = LocalBinder()
    private val ring = AudioRingBuffer(44100 * 15)

    @Volatile private var running = false
    @Volatile private var rmsDbfs = -120.0
    @Volatile private var peakDbfs = -120.0
    @Volatile private var baselineSeconds = 0.0
    @Volatile private var baselineComplete = false
    @Volatile private var framesCaptured = 0L
    @Volatile private var lastError: String? = null

    private var audioRecord: AudioRecord? = null
    private var worker: Thread? = null

    override fun onBind(intent: Intent?): IBinder = binder

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startMonitoring()
            ACTION_STOP -> stopMonitoring()
        }
        return START_NOT_STICKY
    }

    fun snapshot(): Snapshot = Snapshot(
        running = running,
        sampleRate = SAMPLE_RATE,
        rmsDbfs = rmsDbfs,
        peakDbfs = peakDbfs,
        baselineSeconds = baselineSeconds,
        baselineComplete = baselineComplete,
        framesCaptured = framesCaptured,
        lastError = lastError
    )

    private fun buildRecorder(): AudioRecord {
        val minBuffer = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        )
        require(minBuffer > 0) { "AudioRecord.getMinBufferSize failed: $minBuffer" }

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
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            lastError = "RECORD_AUDIO permission not granted"
            stopSelf()
            return
        }

        startForeground(NOTIFICATION_ID, notification("Starting microphone boundary…"))

        try {
            audioRecord = buildRecorder()
            check(audioRecord?.state == AudioRecord.STATE_INITIALIZED) { "AudioRecord did not initialize" }
            ring.clear()
            framesCaptured = 0
            baselineSeconds = 0.0
            baselineComplete = false
            lastError = null
            audioRecord!!.startRecording()
            running = true

            worker = Thread({
                captureLoop()
            }, "BCI-AudioBoundary").also { it.start() }
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
            val n = audioRecord?.read(block, 0, block.size, AudioRecord.READ_BLOCKING) ?: -1
            if (n <= 0) {
                if (running) lastError = "AudioRecord.read returned $n"
                continue
            }

            ring.write(block, n)
            framesCaptured += n
            baselineSeconds = (framesCaptured.toDouble() / SAMPLE_RATE).coerceAtMost(BASELINE_SECONDS)
            baselineComplete = baselineSeconds >= BASELINE_SECONDS

            var sumSq = 0.0
            var peak = 0
            for (i in 0 until n) {
                val v = block[i].toInt()
                sumSq += v.toDouble() * v.toDouble()
                val a = kotlin.math.abs(v)
                if (a > peak) peak = a
            }

            val rms = sqrt(sumSq / n.coerceAtLeast(1))
            rmsDbfs = if (rms > 0.0) 20.0 * log10(rms / 32768.0) else -120.0
            peakDbfs = if (peak > 0) 20.0 * log10(peak.toDouble() / 32768.0) else -120.0
        }
    }

    private fun stopMonitoring() {
        running = false
        try { audioRecord?.stop() } catch (_: Throwable) {}
        try { worker?.join(1200) } catch (_: InterruptedException) {}
        worker = null
        audioRecord?.release()
        audioRecord = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        running = false
        try { audioRecord?.stop() } catch (_: Throwable) {}
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
        channel.description = "Foreground microphone analysis"
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun notification(text: String): Notification {
        val pending = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("BCIWhisper")
            .setContentText(text)
            .setOngoing(true)
            .setContentIntent(pending)
            .build()
    }

    companion object {
        const val ACTION_START = "org.beaconcomputinginitiative.bciwhisper.START"
        const val ACTION_STOP = "org.beaconcomputinginitiative.bciwhisper.STOP"
        private const val CHANNEL_ID = "bciwhisper_audio"
        private const val NOTIFICATION_ID = 5201
        private const val SAMPLE_RATE = 44100
        private const val BASELINE_SECONDS = 60.0
    }
}
