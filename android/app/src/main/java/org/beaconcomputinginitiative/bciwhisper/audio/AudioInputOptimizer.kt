package org.beaconcomputinginitiative.bciwhisper.audio

import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.media.AudioRecord
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.AutomaticGainControl
import android.media.audiofx.NoiseSuppressor

class AudioInputOptimizer(
    context: Context
) {
    data class Capability(
        val label: String,
        val sampleRates: IntArray,
        val channelCounts: IntArray
    )

    data class ProcessingState(
        val automaticGainControlDisabled: Boolean,
        val noiseSuppressorDisabled: Boolean,
        val acousticEchoCancelerDisabled: Boolean
    )

    private val audioManager =
        context.getSystemService(
            AudioManager::class.java
        )

    fun builtInMicrophone(): AudioDeviceInfo? =
        audioManager
            .getDevices(
                AudioManager.GET_DEVICES_INPUTS
            )
            .firstOrNull {
                it.type ==
                    AudioDeviceInfo.TYPE_BUILTIN_MIC
            }

    fun capability(
        device: AudioDeviceInfo?,
        fallbackLabel: String
    ): Capability {
        if (device == null) {
            return Capability(
                label = fallbackLabel,
                sampleRates = intArrayOf(),
                channelCounts = intArrayOf()
            )
        }

        return Capability(
            label =
                device.productName
                    ?.toString()
                    ?.takeIf { it.isNotBlank() }
                    ?: fallbackLabel,
            sampleRates =
                device.sampleRates
                    .filter { it > 0 }
                    .sortedDescending()
                    .toIntArray(),
            channelCounts =
                device.channelCounts
                    .filter { it > 0 }
                    .sortedArrayDescending()
        )
    }

    fun prefer(
        recorder: AudioRecord,
        device: AudioDeviceInfo?
    ): Boolean =
        device != null &&
            recorder.setPreferredDevice(
                device
            )

    fun disableVoiceProcessing(
        recorder: AudioRecord
    ): ProcessingState {
        val session =
            recorder.audioSessionId

        val agc =
            if (
                session > 0 &&
                AutomaticGainControl.isAvailable()
            ) {
                runCatching {
                    AutomaticGainControl
                        .create(session)
                        ?.also {
                            it.enabled = false
                        }
                }.getOrNull()
            } else {
                null
            }

        val ns =
            if (
                session > 0 &&
                NoiseSuppressor.isAvailable()
            ) {
                runCatching {
                    NoiseSuppressor
                        .create(session)
                        ?.also {
                            it.enabled = false
                        }
                }.getOrNull()
            } else {
                null
            }

        val aec =
            if (
                session > 0 &&
                AcousticEchoCanceler.isAvailable()
            ) {
                runCatching {
                    AcousticEchoCanceler
                        .create(session)
                        ?.also {
                            it.enabled = false
                        }
                }.getOrNull()
            } else {
                null
            }

        val state =
            ProcessingState(
                automaticGainControlDisabled =
                    agc?.enabled == false,
                noiseSuppressorDisabled =
                    ns?.enabled == false,
                acousticEchoCancelerDisabled =
                    aec?.enabled == false
            )

        agc?.release()
        ns?.release()
        aec?.release()

        return state
    }

    fun describe(
        capability: Capability,
        processing: ProcessingState
    ): String {
        val rates =
            if (
                capability.sampleRates
                    .isEmpty()
            ) {
                "rate:auto"
            } else {
                "rates:" +
                    capability.sampleRates
                        .take(4)
                        .joinToString("/")
            }

        val channels =
            if (
                capability.channelCounts
                    .isEmpty()
            ) {
                "channels:auto"
            } else {
                "channels:" +
                    capability.channelCounts
                        .joinToString("/")
            }

        val rawPath =
            listOf(
                processing.automaticGainControlDisabled,
                processing.noiseSuppressorDisabled,
                processing.acousticEchoCancelerDisabled
            ).count { it }

        return (
            capability.label +
                " • " +
                rates +
                " • " +
                channels +
                " • raw-processing controls " +
                rawPath +
                "/3"
            )
    }
}
