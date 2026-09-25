"""Allow `python -m mathvault` to work — find the cli module."""
import sys
from pathlib import Path

# Make sure the project root is on the path
_root = str(Path(__file__).parent.parent.resolve())
if _root not in sys.path:
    sys.path.insert(0, _root)

from cli.mathvault import cli

if __name__ == "__main__":
    cli()
