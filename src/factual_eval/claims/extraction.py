"""Compatibility import; implementation: factual_eval.fase3_pipeline.claims.extraction."""
import importlib as _importlib
import sys as _sys
if __name__ == "factual_eval.claims.extraction":
    _sys.modules[__name__] = _importlib.import_module("factual_eval.fase3_pipeline.claims.extraction")
else:
    from pathlib import Path as _Path
    __file__ = str(_Path(__file__).resolve().parents[1] / 'fase3_pipeline/claims/extraction.py')
    __package__ = "factual_eval.fase3_pipeline.claims"
    exec(compile(_Path(__file__).read_text(encoding="utf-8"), __file__, "exec"), globals())
