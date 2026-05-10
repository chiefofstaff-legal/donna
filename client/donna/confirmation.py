"""Format pipeline results as natural confirmation speech.

DONNA reads back what she captured so the lawyer can verify without
looking at a screen.

Usage::

    from donna.confirmation import ConfirmationFormatter
    formatter = ConfirmationFormatter()
    text = formatter.format(time_entry)
    # → "Logged: 90 minutes on the Smith motion. Drafting. Confidence high."
"""

from __future__ import annotations

from donna.models import ClarifyRequest, IntentType, Task, TimeEntry


def _plural(n: int, unit: str) -> str:
    """Render a count + unit with English pluralisation: 1 hour, 2 hours."""
    return f"{n} {unit}" if n == 1 else f"{n} {unit}s"


class ConfirmationFormatter:
    """Converts pipeline results into human-readable confirmation strings.

    All output is designed to be spoken aloud — concise, natural,
    unambiguous. No markdown, no JSON, no abbreviations.
    """

    def format(self, result: TimeEntry | Task | ClarifyRequest) -> str:
        """Return a natural-language confirmation string for *result*."""
        if isinstance(result, TimeEntry):
            return self._format_time_entry(result)
        if isinstance(result, Task):
            return self._format_task(result)
        if isinstance(result, ClarifyRequest):
            return self._format_clarify(result)
        return "Done."

    # ------------------------------------------------------------------
    # Per-type formatters
    # ------------------------------------------------------------------

    def _format_time_entry(self, entry: TimeEntry) -> str:
        parts: list[str] = ["Logged."]

        duration = self._duration_phrase(entry.duration_hours)
        if duration:
            parts.append(duration)

        if entry.matter:
            parts.append(f"Matter: {entry.matter}.")

        if entry.activity:
            parts.append(f"{entry.activity.capitalize()}.")

        if entry.narrative:
            parts.append(entry.narrative.rstrip(".") + ".")

        parts.append(self._confidence_phrase(entry.confidence))
        return " ".join(parts)

    def _format_task(self, task: Task) -> str:
        parts: list[str] = ["Task delegated."]

        if task.assignee:
            parts.append(f"Assigned to {task.assignee}.")

        if task.task:
            parts.append(task.task.rstrip(".") + ".")

        if task.deadline:
            parts.append(f"Due {task.deadline}.")

        if task.matter:
            parts.append(f"Matter: {task.matter}.")

        parts.append(self._confidence_phrase(task.confidence))
        return " ".join(parts)

    def _format_clarify(self, req: ClarifyRequest) -> str:
        intent_label = (
            "time entry" if req.intent_type == IntentType.TIME_ENTRY else "delegation"
        )
        return f"I need a bit more detail for the {intent_label}. {req.question}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _duration_phrase(duration_hours: float | None) -> str:
        if not duration_hours:
            return ""
        total_minutes = round(duration_hours * 60)
        hours, minutes = divmod(total_minutes, 60)
        if hours and minutes:
            return f"{_plural(hours, 'hour')} and {_plural(minutes, 'minute')}."
        if hours:
            return f"{_plural(hours, 'hour')}."
        return f"{_plural(total_minutes, 'minute')}."

    @staticmethod
    def _confidence_phrase(confidence: float) -> str:
        if confidence >= 0.9:
            return "Confidence high."
        if confidence >= 0.7:
            return "Confidence good."
        if confidence >= 0.5:
            return "Low confidence — please verify."
        return "Very low confidence — please review."
