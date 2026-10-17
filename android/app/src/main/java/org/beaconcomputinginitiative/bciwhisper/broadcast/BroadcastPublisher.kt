package org.beaconcomputinginitiative.bciwhisper.broadcast

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.math.min

class BroadcastPublisher {
    enum class State {
        OFFLINE,
        CONNECTING,
        LIVE,
        RETRYING,
        ERROR
    }

    data class Snapshot(
        val state: State,
        val bytesSent: Long,
        val droppedFrames: Long,
        val lastError: String?
    )

    private val client = OkHttpClient.Builder()
        .pingInterval(15, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    private val scheduler = Executors.newSingleThreadScheduledExecutor { runnable ->
        Thread(runnable, "BCI-Broadcast-Reconnect").apply { isDaemon = true }
    }

    @Volatile private var state = State.OFFLINE
    @Volatile private var lastError: String? = null
    @Volatile private var bytesSent = 0L
    @Volatile private var droppedFrames = 0L
    @Volatile private var requested = false

    private var url = ""
    private var token = ""
    private var retryAttempt = 0
    private var socket: WebSocket? = null

    @Synchronized
    fun start(publishUrl: String, publisherToken: String) {
        require(publishUrl.startsWith("wss://")) {
            "BCI mobile broadcast requires a secure wss:// gateway URL"
        }
        require(publisherToken.isNotBlank()) {
            "Publisher token is required"
        }

        requested = true
        url = publishUrl
        token = publisherToken
        retryAttempt = 0
        bytesSent = 0
        droppedFrames = 0
        lastError = null

        socket?.cancel()
        socket = null
        connect()
    }

    @Synchronized
    fun stop() {
        requested = false
        retryAttempt = 0
        lastError = null
        state = State.OFFLINE
        socket?.close(1000, "operator_stop")
        socket = null
        token = ""
    }

    fun snapshot(): Snapshot = Snapshot(
        state = state,
        bytesSent = bytesSent,
        droppedFrames = droppedFrames,
        lastError = lastError
    )

    fun submitPcm(block: ShortArray, count: Int) {
        val ws = socket ?: return
        if (state != State.LIVE) return

        if (ws.queueSize() > MAX_WEBSOCKET_QUEUE_BYTES) {
            droppedFrames += 1
            return
        }

        val n = count.coerceAtMost(block.size)
        val pcm = ByteArray(n * 2)
        var out = 0

        for (i in 0 until n) {
            val value = block[i].toInt()
            pcm[out++] = (value and 0xff).toByte()
            pcm[out++] = ((value ushr 8) and 0xff).toByte()
        }

        if (ws.send(pcm.toByteString())) {
            bytesSent += pcm.size
        } else {
            droppedFrames += 1
        }
    }

    @Synchronized
    private fun connect() {
        if (!requested) return

        state = if (retryAttempt == 0) State.CONNECTING else State.RETRYING

        val request = Request.Builder()
            .url(url)
            .header("Authorization", "Bearer $token")
            .header("X-BCI-Publisher-ID", "bciwhisper-android")
            .build()

        socket = client.newWebSocket(
            request,
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    lastError = null
                    webSocket.send(
                        """{"type":"hello","protocol":"bci-broadcast-v1","codec":"pcm_s16le","sampleRate":44100,"channels":1,"bitrateKbps":128}"""
                    )
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    if (
                        text.contains("\"type\":\"hello_ack\"") ||
                        (text.contains("\"type\"") && text.contains("hello_ack"))
                    ) {
                        retryAttempt = 0
                        lastError = null
                        state = State.LIVE
                    }
                }

                override fun onFailure(
                    webSocket: WebSocket,
                    t: Throwable,
                    response: Response?
                ) {
                    lastError = buildString {
                        append(t::class.simpleName ?: "Broadcast error")
                        if (!t.message.isNullOrBlank()) {
                            append(": ")
                            append(t.message)
                        }
                        if (response != null) {
                            append(" (HTTP ")
                            append(response.code)
                            append(")")
                        }
                    }
                    socket = null
                    scheduleReconnect()
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    socket = null
                    if (requested) {
                        lastError = "Broadcast connection closed ($code): $reason"
                        scheduleReconnect()
                    } else {
                        state = State.OFFLINE
                    }
                }
            }
        )
    }

    @Synchronized
    private fun scheduleReconnect() {
        if (!requested) {
            state = State.OFFLINE
            return
        }

        retryAttempt += 1
        state = State.RETRYING

        val delaySeconds = min(30L, 1L shl min(retryAttempt, 5))

        scheduler.schedule(
            {
                synchronized(this) {
                    if (requested && socket == null) {
                        connect()
                    }
                }
            },
            delaySeconds,
            TimeUnit.SECONDS
        )
    }

    companion object {
        private const val MAX_WEBSOCKET_QUEUE_BYTES = 512L * 1024L
    }
}
