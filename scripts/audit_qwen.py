#!/usr/bin/env python3
"""Compatibility launcher; canonical: scripts/avaliacao_automatica/audit_qwen.py."""
from pathlib import Path
import runpy
if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'avaliacao_automatica' / 'audit_qwen.py'), run_name='__main__')
