#!/usr/bin/env python3
"""DSP operational lab runner — host direct and webshell remote execution."""

from __future__ import annotations

import sys
from pathlib import Path

_DSP_ROOT = Path(__file__).resolve().parent.parent
if str(_DSP_ROOT) not in sys.path:
    sys.path.insert(0, str(_DSP_ROOT))

from dsp.lab.operational_runner import main

if __name__ == "__main__":
    raise SystemExit(main())
