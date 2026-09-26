"""Compatibility package for the sentinel project."""

from sentinel_project.models.model import (
    Attempt,
    Message,
    TargetRequest,
    TargetResponse,
    ToolCall,
    Verdict,
)

__all__ = [
    "Attempt",
    "Message",
    "TargetRequest",
    "TargetResponse",
    "ToolCall",
    "Verdict",
]
