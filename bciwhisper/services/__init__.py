# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.1 | Engineering Build 2026.10.22-r6.35.1
# Developer Seal: CJB-DEV-2026
# Canonical Payload SHA-256: 933002a3fb9318fc884c34d83cfceafeeab9e683322d6e1a3294c438727ff88e
# Integrity rule: hash covers this file's payload below this header, if and only if the payload is unchanged.

"""Application-service layer for BCIWhisper.

Services coordinate domain modules without importing presentation code.
"""

from .transcription import (
    BackendDescriptor,
    TranscriptionService,
    TranscriptionServiceState,
)

__all__ = [
    "BackendDescriptor",
    "TranscriptionService",
    "TranscriptionServiceState",
]
