"""Estudo IA — automação diária de estudos."""

import sys

from estudo_ia.config import carregar_config
from estudo_ia.db import criar_engine


def main() -> None:
    """Ponto de entrada do comando `uv run estudo-ia <comando>`.

    Por enquanto só existe `config` e `iniciar-banco`; os outros comandos
    (ingerir, pacote...) chegam nas próximas fases.
    """
    comando = sys.argv[1] if len(sys.argv) > 1 else "ajuda"
    config = carregar_config()

    if comando == "config":
        for nome, valor in config.resumo_seguro().items():
            print(f"{nome:22} {valor}")
    elif comando == "iniciar-banco":
        criar_engine(config.caminho_banco)
        print(f"Banco pronto em {config.caminho_banco}")
    else:
        print("Comandos disponíveis: config, iniciar-banco")
