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
    sub.add_parser("bot", help="liga o bot do Telegram")
    video = sub.add_parser("video", help="gera o vídeo de um pacote já gerado")
    video.add_argument("--pasta", default="data/pacotes/teste", help="pasta do pacote (com pacote.json)")
    podcast = sub.add_parser("podcast", help="gera o podcast de um pacote já gerado")
    podcast.add_argument("--pasta", default="data/pacotes/teste", help="pasta do pacote (com pacote.json)")
    podcast.add_argument("--fallback", action="store_true", help="pula o NotebookLM e usa o Gemini TTS")
    pacote = sub.add_parser("pacote", help="gera o pacote da próxima sessão")
    pacote.add_argument("--teste", action="store_true", help="gera em data/pacotes/teste sem registrar no banco")
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

    elif args.comando == "pacote":
        from estudo_ia.pacote.servico import criar_pacote

        arquivos = criar_pacote(engine, config, teste=args.teste)
        print(f"Pacote pronto: {arquivos.titulo}")
        print(f"  HTML: {arquivos.html}")
        print(f"  PDF:  {arquivos.pdf}")

    elif args.comando == "podcast":
        from pathlib import Path

        from estudo_ia.pacote.gerador import carregar_pacote
        from estudo_ia.podcast.servico import gerar_podcast

        pasta = Path(args.pasta)
        resultado = gerar_podcast(carregar_pacote(pasta / "pacote.json"), pasta, config,
                                  forcar_fallback=args.fallback)
        for aviso in resultado.avisos:
            print(f"! {aviso}")
        print(f"Podcast pronto ({resultado.origem}, {resultado.minutos} min): {resultado.mp3}")

    elif args.comando == "video":
        from pathlib import Path

        from estudo_ia.pacote.gerador import carregar_pacote
        from estudo_ia.video.servico import gerar_video

        pasta = Path(args.pasta)
        resultado = gerar_video(carregar_pacote(pasta / "pacote.json"), pasta, config)
        for aviso in resultado.avisos:
            print(f"! {aviso}")
        print(f"Vídeo pronto ({resultado.minutos} min, {resultado.megabytes} MB): {resultado.mp4}")

    elif args.comando == "bot":
        from estudo_ia.bot.app import rodar

        rodar(config, engine)
