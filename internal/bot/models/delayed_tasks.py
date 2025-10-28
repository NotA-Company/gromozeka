"""
Delayed Tasks: Models for delayed task execution
"""

# Re-export DelayedTaskFunction and DelayedTask
from internal.services.queue_service.types import DelayedTask, DelayedTaskFunction

__all__ = ["DelayedTaskFunction", "DelayedTask"]
