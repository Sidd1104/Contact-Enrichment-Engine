"""
src/ai/ai_metrics.py
======================
Tracks and serializes telemetry regarding AI provider utilization, avoided calls, and token usage.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)


class AIMetrics:
    """
    Measures AI calls, avoided queries, confidence boosts, and token counts.
    """

    def __init__(self, filepath: str = "logs/ai_metrics.json") -> None:
        self.filepath = Path(filepath)
        
        self.ai_calls = 0
        self.ai_avoided = 0
        self.confidence_improvements = 0
        self.total_enrichment_time = 0.0
        self.sessions_count = 0
        
        # Token usage trackers
        self.prompt_tokens = 0
        self.candidates_tokens = 0
        self.total_tokens = 0

        self.load()

    def load(self) -> None:
        """Loads state from file if it exists."""
        if self.filepath.exists():
            try:
                with open(self.filepath, "r") as f:
                    data = json.load(f)
                
                counts = data.get("counts", {})
                self.ai_calls = counts.get("ai_calls", 0)
                self.ai_avoided = counts.get("ai_avoided", 0)
                self.confidence_improvements = counts.get("confidence_improvements", 0)

                tokens = data.get("tokens", {})
                self.prompt_tokens = tokens.get("prompt_tokens", 0)
                self.candidates_tokens = tokens.get("candidates_tokens", 0)
                self.total_tokens = tokens.get("total_tokens", 0)

                perf = data.get("performance", {})
                self.total_enrichment_time = perf.get("total_enrichment_time", 0.0)
                self.sessions_count = perf.get("sessions_count", 0)
            except Exception as e:
                logger.warning(f"Could not load AI metrics: {e}. Starting fresh.")

    def record_ai_call(self, latency: float, prompt_tok: int = 0, cand_tok: int = 0) -> None:
        self.ai_calls += 1
        self.sessions_count += 1
        self.total_enrichment_time += latency
        self.prompt_tokens += prompt_tok
        self.candidates_tokens += cand_tok
        self.total_tokens += (prompt_tok + cand_tok)

    def record_ai_avoided(self) -> None:
        self.ai_avoided += 1

    def record_confidence_improvement(self) -> None:
        self.confidence_improvements += 1

    def generate_report(self) -> Dict[str, Any]:
        """Calculates derived metrics and returns a report dictionary."""
        avg_time = (self.total_enrichment_time / self.ai_calls) if self.ai_calls > 0 else 0.0
        
        return {
            "counts": {
                "ai_calls": self.ai_calls,
                "ai_avoided": self.ai_avoided,
                "confidence_improvements": self.confidence_improvements
            },
            "tokens": {
                "prompt_tokens": self.prompt_tokens,
                "candidates_tokens": self.candidates_tokens,
                "total_tokens": self.total_tokens
            },
            "performance": {
                "total_enrichment_time": round(self.total_enrichment_time, 3),
                "ai_sessions_count": self.sessions_count,
                "average_enrichment_time_seconds": round(avg_time, 3)
            }
        }

    def save(self) -> None:
        """Saves current report to json file."""
        report = self.generate_report()
        try:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(self.filepath, "w") as f:
                json.dump(report, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save AI metrics: {e}")
