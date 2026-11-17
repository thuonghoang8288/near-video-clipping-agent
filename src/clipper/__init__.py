"""Video Clipping Agent — local, open-source, no paid APIs.

Turns one long video into short, platform-ready clips with burned-in
captions and a report explaining why each moment was chosen.
"""
from .pipeline import run

__all__ = ["run"]
__version__ = "0.1.0"
