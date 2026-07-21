"""Frozen entry point for the Bose on Desktop tray app (PyInstaller target).

Running from source, the ``pybmap`` package lives under ref-bosectl/python and
is normally found via a .pth file; add it explicitly so this launcher also works
without that .pth. When frozen, PyInstaller bundles pybmap into the exe and this
path insert is skipped.
"""

import os
import sys

if not getattr(sys, "frozen", False):
    _pybmap_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "ref-bosectl", "python")
    if _pybmap_path not in sys.path:
        sys.path.insert(0, _pybmap_path)

from bosewin.gui import main

if __name__ == "__main__":
    main()
