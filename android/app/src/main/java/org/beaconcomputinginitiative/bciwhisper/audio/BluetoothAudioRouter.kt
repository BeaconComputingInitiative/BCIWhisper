package org.beaconcomputinginitiative.bciwhisper.audio

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.media.AudioRecord
import android.os.Build

class BluetoothAudioRouter(
    private val context: Context
) {
    private val audioManager =
        context.getSystemService(
            AudioManager::class.java
        )

    data class RouteResult(
        val routed: Boolean,
        val label: String,
        val device: AudioDeviceInfo?
    )

    fun route(): RouteResult {
        if (
            Build.VERSION.SDK_INT >= 31 &&
            context.checkSelfPermission(
                Manifest.permission.BLUETOOTH_CONNECT
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            return RouteResult(
                false,
                "Nearby devices permission required",
                null
            )
        }

        val device =
            if (Build.VERSION.SDK_INT >= 31) {
                audioManager
                    .availableCommunicationDevices
                    .firstOrNull {
                        it.type ==
                            AudioDeviceInfo.TYPE_BLUETOOTH_SCO
                    }
            } else {
                audioManager
                    .getDevices(
                        AudioManager.GET_DEVICES_INPUTS
                    )
                    .firstOrNull {
                        it.type ==
                            AudioDeviceInfo.TYPE_BLUETOOTH_SCO
                    }
            }

        if (device == null) {
            return RouteResult(
                false,
                "No paired Bluetooth headset microphone is available",
                null
            )
        }

        val accepted =
            if (Build.VERSION.SDK_INT >= 31) {
                audioManager.setCommunicationDevice(device)
            } else {
                @Suppress("DEPRECATION")
                audioManager.startBluetoothSco()
                @Suppress("DEPRECATION")
                run {
                    audioManager.isBluetoothScoOn = true
                }
                true
            }

        return RouteResult(
            accepted,
            if (accepted) {
                device.productName
                    ?.toString()
                    ?.takeIf { it.isNotBlank() }
                    ?: "Bluetooth headset microphone"
            } else {
                "Bluetooth audio route was rejected"
            },
            if (accepted) device else null
        )
    }

    fun prefer(
        recorder: AudioRecord,
        device: AudioDeviceInfo?
    ): Boolean =
        device != null &&
            recorder.setPreferredDevice(device)

    fun clear() {
        if (Build.VERSION.SDK_INT >= 31) {
            audioManager.clearCommunicationDevice()
        } else {
            @Suppress("DEPRECATION")
            run {
                audioManager.isBluetoothScoOn = false
                audioManager.stopBluetoothSco()
            }
        }
    }
}
