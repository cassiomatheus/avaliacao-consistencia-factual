"""Compatibility import; implementation: factual_eval.fase2_injecao.validation."""
import importlib as _importlib
import sys as _sys
if __name__ == "factual_eval.data.validation":
    _sys.modules[__name__] = _importlib.import_module("factual_eval.fase2_injecao.validation")
else:
    from pathlib import Path as _Path
    __file__ = str(_Path(__file__).resolve().parents[1] / 'fase2_injecao/validation.py')
    __package__ = "factual_eval.fase2_injecao"
    exec(compile(_Path(__file__).read_text(encoding="utf-8"), __file__, "exec"), globals())
