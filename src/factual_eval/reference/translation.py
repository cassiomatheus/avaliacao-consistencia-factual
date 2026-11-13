"""Compatibility import; implementation: factual_eval.fase1_referencia.translation."""
import importlib as _importlib
import sys as _sys
if __name__ == "factual_eval.reference.translation":
    _sys.modules[__name__] = _importlib.import_module("factual_eval.fase1_referencia.translation")
else:
    from pathlib import Path as _Path
    __file__ = str(_Path(__file__).resolve().parents[1] / 'fase1_referencia/translation.py')
    __package__ = "factual_eval.fase1_referencia"
    exec(compile(_Path(__file__).read_text(encoding="utf-8"), __file__, "exec"), globals())
