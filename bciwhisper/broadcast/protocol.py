PROTOCOL = "bci-broadcast-v1"
DEFAULT_STREAM_ID = "bciwhisper-main"
DEFAULT_CODEC = "mp3"

def publisher_hello(sample_rate, channels=1, bitrate_kbps=128):
    return {
        "type": "hello",
        "protocol": PROTOCOL,
        "codec": DEFAULT_CODEC,
        "sampleRate": int(sample_rate),
        "channels": int(channels),
        "bitrateKbps": int(bitrate_kbps),
    }
