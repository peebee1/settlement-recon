import sys
from pathlib import Path

ARTIFACT = Path(__file__).resolve().parents[1]
if str(ARTIFACT) not in sys.path:
    sys.path.insert(0, str(ARTIFACT))
