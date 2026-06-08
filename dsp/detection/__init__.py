"""Detection Adapter Layer — S3 (Detection Confirmed) consumer."""

from dsp.detection.base import DetectionAdapter
from dsp.detection.manager import DetectionManager
from dsp.detection.models import (
    AlertEvidence,
    AnalyticsEvidence,
    ArtifactEvidence,
    CorrelationContext,
    EntityEvidence,
    EvidencePack,
    S3Result,
    S3Status,
    TimelineEvidence,
)

__all__ = [
    "AlertEvidence",
    "AnalyticsEvidence",
    "ArtifactEvidence",
    "CorrelationContext",
    "DetectionAdapter",
    "DetectionManager",
    "EntityEvidence",
    "EvidencePack",
    "S3Result",
    "S3Status",
    "TimelineEvidence",
]
