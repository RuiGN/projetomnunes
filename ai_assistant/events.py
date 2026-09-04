"""Domain events and signals for AI assistant and clinical drafting governance."""

from __future__ import annotations

from dataclasses import dataclass

from django.dispatch import Signal

from core.events import DomainEvent as CoreDomainEvent


@dataclass(frozen=True, slots=True)
class DomainEvent(CoreDomainEvent):
    """Base domain event for AI assistant operations."""


# Django signals for decoupled observation
ai_draft_created = Signal()
ai_draft_reviewed = Signal()
ai_guardrail_triggered = Signal()
ai_kill_switch_toggled = Signal()
ai_benchmark_run_completed = Signal()

