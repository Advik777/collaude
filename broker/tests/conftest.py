"""Test bootstrap for the broker unit tests (docs §13, Layer 1).

Puts the broker/ directory on sys.path so the modules under test import as
top-level names (`broker`, `context_store`, `conflict_detector`,
`session_registry`) — matching broker.py's own script-style import fallback.
"""

import os
import sys

BROKER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BROKER_DIR not in sys.path:
    sys.path.insert(0, BROKER_DIR)
