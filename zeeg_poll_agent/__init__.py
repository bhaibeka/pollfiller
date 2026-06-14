"""zeeg-poll-agent: auto-fill meeting polls using Zeeg calendar availability."""
from .agent import PollAgent
from .config import Config
from .models import BusyInterval, Identity, PollData, SelectionResult, TimeSlot

__version__ = "1.0.0"
__all__ = [
    "PollAgent",
    "Config",
    "TimeSlot",
    "BusyInterval",
    "Identity",
    "PollData",
    "SelectionResult",
]
