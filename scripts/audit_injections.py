#!/usr/bin/env python3
"""Compatibility launcher; canonical: scripts/fase2_injecao/audit_injections.py."""
from pathlib import Path
import runpy
if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'fase2_injecao' / 'audit_injections.py'), run_name='__main__')
