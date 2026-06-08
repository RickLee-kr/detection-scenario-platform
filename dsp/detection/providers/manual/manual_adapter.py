"""Manual S3 evidence adapter — operator-confirmed detection validation (default)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from dsp.detection.base import DetectionAdapter
from dsp.detection.models import (
    CorrelationContext,
    EvidencePack,
    S3Result,
    S3Status,
)

MANUAL_REVIEW_REASON = "manual_review_required"


class ManualDetectionAdapter(DetectionAdapter):
    """Generate manual S3 evidence templates without vendor API access."""

    @property
    def vendor_id(self) -> str:
        return "manual"

    def collect_evidence(self, context: CorrelationContext) -> EvidencePack:
        return EvidencePack(
            run_id=context.run_id,
            scenario_id=context.scenario_id,
            vendor=self.vendor_id,
        )

    def validate_detection(
        self,
        context: CorrelationContext,
        evidence: EvidencePack,
    ) -> S3Result:
        if context.s2_decision != "success":
            return S3Result(
                run_id=context.run_id,
                scenario=context.scenario_id,
                status=S3Status.S3_INCONCLUSIVE,
                vendor=self.vendor_id,
                evidence_count=0,
                timestamp=datetime.now(timezone.utc),
                correlation_context=context,
                reason=(
                    f"s2_decision={context.s2_decision}; "
                    "manual S3 review skipped until S2 success"
                ),
                evidence_pack=evidence,
            )

        return S3Result(
            run_id=context.run_id,
            scenario=context.scenario_id,
            status=S3Status.S3_INCONCLUSIVE,
            vendor=self.vendor_id,
            evidence_count=0,
            timestamp=datetime.now(timezone.utc),
            correlation_context=context,
            reason=MANUAL_REVIEW_REASON,
            evidence_pack=evidence,
        )

    def build_evidence_pack(
        self,
        context: CorrelationContext,
        evidence: EvidencePack,
        s3_result: S3Result,
        output_dir: Path,
    ) -> Path:
        manual_dir = output_dir / "evidence" / context.run_id / self.vendor_id
        manual_dir.mkdir(parents=True, exist_ok=True)

        (manual_dir / "s3_manual_checklist.md").write_text(
            _render_checklist(context, s3_result),
            encoding="utf-8",
        )
        (manual_dir / "correlation_notes.md").write_text(
            _render_correlation_notes(context),
            encoding="utf-8",
        )
        (manual_dir / "stellar_ui_evidence_template.md").write_text(
            _render_ui_template(context),
            encoding="utf-8",
        )
        return manual_dir


def _fmt_dt(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _render_checklist(context: CorrelationContext, s3_result: S3Result) -> str:
    return f"""# S3 Manual Detection Checklist

**Run ID:** `{context.run_id}`
**Scenario:** `{context.scenario_id}`
**Status:** `{s3_result.status.value}` (pending operator review)
**Reason:** `{s3_result.reason}`

## Pre-filled correlation context

| Field | Value |
|-------|-------|
| Time window start | {_fmt_dt(context.time_window_start)} |
| Time window end | {_fmt_dt(context.time_window_end)} |
| Source IP | {context.source_ip or '(fill from report)'} |
| Destination IP | {context.destination_ip or '(fill from report)'} |
| S2 decision | {context.s2_decision or 'unknown'} |
| Dry run | {context.dry_run} |

## Operator checklist

- [ ] DSP run completed; S2 validation reviewed in `report.md`
- [ ] Stellar UI opened for the run time window
- [ ] Search performed using source/destination IP and scenario type
- [ ] Alert ID(s) captured (if observed)
- [ ] Screenshot(s) saved alongside this evidence pack
- [ ] `correlation_notes.md` completed with alert ↔ run mapping
- [ ] S3 outcome marked manually: CONFIRMED / NOT_OBSERVED / INCONCLUSIVE

## References

- DSP report: `../../report.md`
- Validation: `../../validation.json`
- Event store export: `../../events.jsonl`
"""


def _render_correlation_notes(context: CorrelationContext) -> str:
    return f"""# Correlation Notes

**Run ID:** `{context.run_id}`
**Scenario:** `{context.scenario_id}`

## Time window

- Start: {_fmt_dt(context.time_window_start)}
- End: {_fmt_dt(context.time_window_end)}

## Network context

- Source IP: {context.source_ip or '_pending_'}
- Destination IP: {context.destination_ip or '_pending_'}

## Stellar alert correlation

| Alert ID | Alert name | Observed at (UTC) | Match confidence | Notes |
|----------|------------|-------------------|------------------|-------|
| | | | | |

## Operator conclusion

- [ ] S3_CONFIRMED — alert(s) correlate with DSP traffic evidence
- [ ] S3_NOT_OBSERVED — no matching alert in Stellar for this window
- [ ] S3_INCONCLUSIVE — partial or ambiguous correlation

**Final notes:**

_(Describe correlation rationale, screenshots taken, and any follow-up actions.)_
"""


def _render_ui_template(context: CorrelationContext) -> str:
    return f"""# Stellar UI Evidence Template

Use this template when capturing manual S3 evidence from the Stellar Cyber UI.

## Search parameters

| Parameter | Suggested value |
|-----------|-----------------|
| Run ID | `{context.run_id}` |
| Scenario | `{context.scenario_id}` |
| Time range | {_fmt_dt(context.time_window_start)} → {_fmt_dt(context.time_window_end)} |
| Source IP | {context.source_ip or '(from DSP report)'} |
| Destination IP | {context.destination_ip or '(from DSP report)'} |

## Screenshots to capture

1. **Alert list** — filtered by time window and source IP
2. **Alert detail** — alert ID, severity, rule name, timestamp
3. **Entity / timeline view** — source ↔ destination relationship (if available)
4. **DSP report excerpt** — S2 success metrics for side-by-side comparison

## Manual alert ID entry

```
Alert ID:
Alert name:
Observed at (UTC):
Stellar tenant / cluster:
Screenshot filename(s):
```

## Notes

- DSP does **not** require Stellar API access for normal S3 validation.
- Complete this template and save screenshots in this directory.
- Update `correlation_notes.md` with final S3 determination.
"""
