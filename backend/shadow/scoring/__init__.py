from __future__ import annotations
from pathlib import Path
from shadow.deps import Deps
from shadow.store.models import Segment


def score_attempt(deps: Deps, segment: Segment, attempt_wav: Path) -> dict | None:
    """Phase 2 implements tone scoring here. Phase 1: no score."""
    return None
