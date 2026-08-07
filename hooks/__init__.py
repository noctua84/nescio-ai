# hooks/ modules are also run as standalone scripts (Claude Code invokes them by
# absolute path), so they import their siblings by bare name (e.g. harvest_nudge
# does `import record_stop`). Put this package directory on sys.path when the
# package is imported, so `from hooks import harvest_nudge` resolves everywhere
# without each caller needing its own sys.path setup.
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
