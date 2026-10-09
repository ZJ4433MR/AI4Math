"""Evidence-only reporting; no model calls or fabricated experiment rows."""

from .report import build_report, load_report_evidence

__all__ = ["build_report", "load_report_evidence"]
