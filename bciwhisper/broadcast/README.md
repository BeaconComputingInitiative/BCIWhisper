# Broadcast layer ownership

This layer owns:

- BroadcastBus
- Go-Live lifecycle
- authenticated publisher
- Bun gateway process manager
- gateway health/admin client
- public telemetry handoff

It does **not** own microphone capture, DSP, recording, or GUI widgets.

## Publisher protocol

Protocol:

```text
bci-broadcast-v1
```

Accepted publisher input codecs:

- `mp3` — forwarded directly to listeners.
- `pcm_s16le` — intended for constrained/mobile publishers; the gateway transcodes the incoming signed 16-bit little-endian PCM stream to MP3 before fan-out.

The mobile Android publisher uses `pcm_s16le` at 44.1 kHz mono and connects outbound through authenticated `wss://`.

## Mobile-network behavior

The Android device does **not** host a public listener socket. It makes one outbound WebSocket connection to a public BCI Broadcast Gateway. Carrier NAT/CGNAT therefore does not require port forwarding on the phone.

A public deployment should terminate TLS and expose the publisher endpoint as `wss://`. The Android application intentionally rejects cleartext `ws://` publisher URLs.

## Local sequence

GO LIVE
-> connect to gateway
-> authenticate publisher
-> hello/ack
-> publish encoded MP3 or PCM16
-> gateway transcodes PCM16 when required
-> mark LIVE

STOP LIVE
-> stop publisher
-> drain/close stream
-> mark OFFLINE
