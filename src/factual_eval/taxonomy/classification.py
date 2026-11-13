"""Compatibility import; implementation: factual_eval.avaliacao_automatica.taxonomy.classification."""
import importlib as _importlib
import sys as _sys
if __name__ == "factual_eval.taxonomy.classification":
    _sys.modules[__name__] = _importlib.import_module("factual_eval.avaliacao_automatica.taxonomy.classification")
else:
    from pathlib import Path as _Path
    __file__ = str(_Path(__file__).resolve().parents[1] / 'avaliacao_automatica/taxonomy/classification.py')
    __package__ = "factual_eval.avaliacao_automatica.taxonomy"
    exec(compile(_Path(__file__).read_text(encoding="utf-8"), __file__, "exec"), globals())
