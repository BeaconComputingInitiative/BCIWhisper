# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.2 | Engineering Build 2026.10.22-r6.35.2
# Developer Seal: CJB-DEV-2026

"""Application-service layer for BCIWhisper.

Services coordinate domain modules without importing presentation code.
"""

from .native_dsp import NativeDSPService
from .transcription import (
    BackendDescriptor,
    TranscriptionService,
    TranscriptionServiceState,
)

__all__ = [
    "BackendDescriptor",
    "NativeDSPService",
    "TranscriptionService",
    "TranscriptionServiceState",
]
