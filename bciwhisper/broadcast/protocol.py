PROTOCOL = "bci-broadcast-v1"
DEFAULT_STREAM_ID = "bciwhisper-main"
DEFAULT_CODEC = "mp3"
SUPPORTED_PUBLISHER_CODECS = frozenset({"mp3", "pcm_s16le"})

def publisher_hello(
    sample_rate,
    channels=1,
    bitrate_kbps=128,
    codec=DEFAULT_CODEC,
):
    codec = str(codec).strip().lower()
    if codec not in SUPPORTED_PUBLISHER_CODECS:
        raise ValueError(f"Unsupported broadcast codec: {codec}")

    return {
        "type": "hello",
        "protocol": PROTOCOL,
        "codec": codec,
        "sampleRate": int(sample_rate),
        "channels": int(channels),
        "bitrateKbps": int(bitrate_kbps),
    }
