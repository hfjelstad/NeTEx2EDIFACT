# conftest.py — NeTEx2EDIFACT/
# Ensures the NeTEx2EDIFACT/ root is on sys.path so that
# `import Converter.*` works in all pytest invocation styles.
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent   # NeTEx2EDIFACT/
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
