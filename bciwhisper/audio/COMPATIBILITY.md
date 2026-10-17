# Audio compatibility

Script 58.1 does not replace the proven `bci_audio/boundary.py` implementation.
That package remains the active process-isolated PortAudio authority during the
migration.

New audio code belongs under `bciwhisper.audio`.

The compatibility boundary is intentional:

`bci_audio.boundary -> PCM/session messages -> BCIWhisper DSP`

No UI code may open input devices directly.
