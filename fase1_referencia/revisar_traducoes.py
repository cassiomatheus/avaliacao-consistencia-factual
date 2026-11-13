#!/usr/bin/env python3
"""Segunda passagem local de fidelidade nos segmentos com alertas de tradução."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from factual_eval.fase1_referencia.translation import OllamaTranslator, revise_flagged_translations


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--model', default='qwen3.5:9b')
    parser.add_argument('--source-only-critical', action='store_true',
                        help='Retraduzir números/siglas sinalizados e catfish sem contexto vizinho ou rascunho')
    args = parser.parse_args()
    revise_flagged_translations(args.input, args.output, OllamaTranslator(args.model),
                                source_only_critical=args.source_only_critical)
