import sys
from pathlib import Path

# Allow bare imports like `from backends.image import ...` in tests,
# mirroring the runtime environment where CWD is src/.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
