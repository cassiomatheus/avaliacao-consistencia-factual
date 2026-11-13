#!/usr/bin/env python3
"""Abra uma auditoria existente com salvamento automático em arquivo local."""
import argparse
from pathlib import Path
import sys
import webbrowser

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from factual_eval.config import project_path
from factual_eval.fase1_referencia.review_server import make_server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--html', required=True, help='avaliacao.html já gerado')
    parser.add_argument('--annotations', help='Arquivo .json de revisão; padrão em outputs/annotations/')
    parser.add_argument('--source', help='Snapshot JSONL report/summary para habilitar revisão integrada')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--open', action='store_true', help='Abrir a URL no navegador')
    args = parser.parse_args()
    html = project_path(args.html)
    annotations = project_path(args.annotations) if args.annotations else None
    if not 0 <= args.port <= 65535:
        parser.error('Porta inválida')
    try:
        from factual_eval.fase1_referencia.workspace import read_rows
        server = make_server(html, annotations, args.port, sources=read_rows(project_path(args.source)) if args.source else None)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Não foi possível abrir a auditoria: {exc}\n')
    url = f'http://127.0.0.1:{server.server_port}/' + ('integrated' if args.source else '')
    print('Auditoria:', url, flush=True)
    print('Arquivo das análises:', server.store.path, flush=True)
    print('Mantenha este terminal aberto. Ctrl+C encerra o serviço; arquivos já salvos permanecem.', flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if server.workspace:
            server.workspace.close()
        server.server_close()
        server.store.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
