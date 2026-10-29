"""Estudo IA — automação diária de estudos."""

import argparse
import sys

from estudo_ia.config import carregar_config
from estudo_ia.db import criar_engine


def main() -> None:
    """Ponto de entrada do comando `uv run estudo-ia <comando>`."""
    sys.stdout.reconfigure(encoding="utf-8")  # acentos certos no terminal do Windows

    parser = argparse.ArgumentParser(prog="estudo-ia")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("config", help="mostra a configuração (sem os segredos)")
    sub.add_parser("iniciar-banco", help="cria o banco SQLite")
    ingerir = sub.add_parser("ingerir", help="lê livros novos e envia ao File Search")
    ingerir.add_argument("--sem-rag", action="store_true", help="só extrai para o banco, sem enviar ao Gemini")
    sub.add_parser("livros", help="lista os livros e o número de capítulos")
    perguntar = sub.add_parser("perguntar", help="faz uma pergunta sobre os livros")
    perguntar.add_argument("pergunta")
    args = parser.parse_args()

    config = carregar_config()

    if args.comando == "config":
        for nome, valor in config.resumo_seguro().items():
            print(f"{nome:24} {valor}")
        return

    engine = criar_engine(config.caminho_banco)

    if args.comando == "iniciar-banco":
        print(f"Banco pronto em {config.caminho_banco}")

    elif args.comando == "ingerir":
        from estudo_ia.ingestao import file_search
        from estudo_ia.ingestao.biblioteca import ingerir_pasta

        resultado = ingerir_pasta(engine, config.biblioteca_dir)
        for livro in resultado.novos:
            print(f"+ {livro}")
        for aviso in resultado.avisos:
            print(f"! {aviso}")
        print(f"{len(resultado.novos)} livros novos, {resultado.ja_existiam} já estavam no banco.")

        if not args.sem_rag:
            cliente = file_search.criar_cliente(config)
            store = file_search.obter_store(cliente, config)
            total = file_search.enviar_pendentes(cliente, store, engine)
            print(f"File Search: {total} capítulos enviados agora.")

    elif args.comando == "livros":
        from estudo_ia.ingestao.biblioteca import listar_livros

        for livro, capitulos, indexados in listar_livros(engine):
            rag = "RAG ok" if indexados == capitulos else f"RAG {indexados}/{capitulos}"
            print(f"{livro.id:3}. {livro.titulo[:55]:55} {capitulos:3} capítulos  [{rag}]")

    elif args.comando == "perguntar":
        from estudo_ia.ingestao import file_search

        cliente = file_search.criar_cliente(config)
        store = file_search.obter_store(cliente, config)
        resposta = file_search.perguntar(cliente, store, config, args.pergunta)
        print(resposta.texto)
        print("\nFontes encontradas pela busca:")
        for fonte in resposta.fontes:
            print(f"  - {fonte}")
