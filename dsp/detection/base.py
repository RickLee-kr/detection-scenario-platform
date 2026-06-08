"""Detection Adapter interface — pluggable vendor consumers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from dsp.detection.models import CorrelationContext, EvidencePack, S3Result


class DetectionAdapter(ABC):
    """Vendor-specific detection consumer. Never a source of truth."""

    @property
    @abstractmethod
    def vendor_id(self) -> str:
        """Stable vendor identifier (e.g. 'stellar')."""

    @abstractmethod
    def collect_evidence(self, context: CorrelationContext) -> EvidencePack:
        """Query vendor APIs and return vendor-neutral evidence."""

    @abstractmethod
    def validate_detection(
        self,
        context: CorrelationContext,
        evidence: EvidencePack,
    ) -> S3Result:
        """Correlate evidence against context and produce S3 status."""

    @abstractmethod
    def build_evidence_pack(
        self,
        context: CorrelationContext,
        evidence: EvidencePack,
        s3_result: S3Result,
        output_dir: Path,
    ) -> Path:
        """Write evidence artifacts under evidence/<run_id>/<vendor>/."""
