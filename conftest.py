import sys, pathlib

_root = pathlib.Path(__file__).resolve().parent
for _p in (_root, _root / "hooks", _root / "scripts"):
    s = str(_p)
    if s not in sys.path:
        sys.path.insert(0, s)
