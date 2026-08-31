"""BusinessIntelligence.ai — business-impact (ROI) estimation package."""

from .roi_estimator import (
    ACTIONABLE_DECISIONS,
    DEFAULT_RECOVERY_RATE,
    MAX_RECOVERY_RATE,
    ROI_ARTIFACT_PATH,
    analyze_event,
    get_roi_summary,
    list_negative_events,
    load_backtest,
    run_backtest,
    save_backtest,
)

__all__ = [
    "ACTIONABLE_DECISIONS",
    "DEFAULT_RECOVERY_RATE",
    "MAX_RECOVERY_RATE",
    "ROI_ARTIFACT_PATH",
    "analyze_event",
    "get_roi_summary",
    "list_negative_events",
    "load_backtest",
    "run_backtest",
    "save_backtest",
]