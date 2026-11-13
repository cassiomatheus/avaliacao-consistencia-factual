"""Evaluated pipeline boundary: claims -> retrieval -> NLI, no reference access."""
import argparse
from factual_eval.cli import main as legacy_main


def main(argv=None):
    import sys
    args=list(sys.argv[1:] if argv is None else argv)
    from factual_eval.cli import parser
    checker=parser('pipeline')
    for action in checker._actions:
        if action.dest in {'from_stage','until_stage'}:action.choices=['claims','retrieval','nli']
    checker.set_defaults(until_stage='nli',output_root='outputs/fase3_pipeline')
    opts=checker.parse_args(args)
    if '--until-stage' not in args:args+=['--until-stage',opts.until_stage]
    if '--output-root' not in args:args+=['--output-root',opts.output_root]
    return legacy_main('pipeline',args)
