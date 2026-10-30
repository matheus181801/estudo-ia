"""Testes da Fase 2: planejador da trilha e formatação das mensagens."""

from estudo_ia.bot.app import encontrar_livro
from estudo_ia.bot.formatacao import dividir, markdown_para_html
from estudo_ia.db import Capitulo, Livro, abrir_sessao, criar_engine
from estudo_ia.trilha import planejador
from estudo_ia.trilha.planejador import MAX_CHARS, planejar


def cap(ordem, chars, inicio, fim):
    return Capitulo(id=ordem, livro_id=1, ordem=ordem, titulo=f"Cap {ordem}",
                    pagina_inicio=inicio, pagina_fim=fim, texto="x" * chars)


def test_junta_capitulos_curtos():
    sessoes = planejar([cap(1, 25_000, 1, 10), cap(2, 25_000, 11, 20), cap(3, 25_000, 21, 30)])
    # 25k + 25k = 50k cabe; somar o terceiro (75k) passaria de 60k.
    assert [len(s.capitulos) for s in sessoes] == [2, 1]
    assert (sessoes[0].pagina_inicio, sessoes[0].pagina_fim) == (1, 20)


def test_divide_capitulo_longo():
    sessoes = planejar([cap(1, 150_000, 1, 90)])
    assert len(sessoes) == 3  # 150k / 50k
    assert sessoes[0].pagina_inicio == 1 and sessoes[-1].pagina_fim == 90
    assert all(s.caracteres <= MAX_CHARS for s in sessoes)


def criar_livro(engine):
    with abrir_sessao(engine) as s:
        livro = Livro(titulo="Cointeligência", autor="Ethan Mollick", arquivo="c.epub", formato="epub")
        s.add(livro)
        s.flush()
        for c in [cap(1, 40_000, 1, 20), cap(2, 40_000, 21, 40)]:
            c.id = None
            c.livro_id = livro.id
            s.add(c)
        s.commit()
        return livro.id


def test_trilha_escolher_e_pular(tmp_path):
    engine = criar_engine(tmp_path / "t.db")
    livro_id = criar_livro(engine)

    assert planejador.situacao_atual(engine) is None
    _, total = planejador.escolher_livro(engine, livro_id)
    assert total == 2

    sit = planejador.situacao_atual(engine)
    assert sit.proxima.ordem == 1 and sit.concluidas == 0
    assert planejador.pular_proxima(engine)
    assert planejador.situacao_atual(engine).proxima.ordem == 2

    # Escolher de novo o mesmo livro não refaz o plano nem perde o progresso.
    planejador.escolher_livro(engine, livro_id)
    assert planejador.situacao_atual(engine).concluidas == 1


def test_encontrar_livro_sem_acento(tmp_path):
    engine = criar_engine(tmp_path / "t.db")
    livro_id = criar_livro(engine)
    assert [l.id for l in encontrar_livro(engine, "cointeligencia")] == [livro_id]
    assert [l.id for l in encontrar_livro(engine, "MOLLICK")] == [livro_id]
    assert [l.id for l in encontrar_livro(engine, str(livro_id))] == [livro_id]
    assert encontrar_livro(engine, "harry potter") == []


def test_markdown_para_html():
    assert markdown_para_html("**RAG** usa *chunks* & <tags>") == "<b>RAG</b> usa <i>chunks</i> &amp; &lt;tags&gt;"
    assert markdown_para_html("## Título") == "<b>Título</b>"


def test_dividir_respeita_limite():
    texto = "\n\n".join(["parágrafo " * 50] * 30)  # ~15 mil caracteres
    partes = dividir(texto, limite=4000)
    assert len(partes) > 1
    assert all(len(p) <= 4000 for p in partes)
    assert "".join(partes).replace("\n", "") == texto.replace("\n", "")


def test_roteador_modelo_hibrido():
    from estudo_ia.bot.roteador import CLAUDE, GEMINI, escolher_caminho

    # Com livro na trilha, pergunta comum vai para o Claude.
    assert escolher_caminho("O que é a fronteira irregular?", tem_livro_ativo=True) == CLAUDE
    # Falar de outros livros ou da biblioteca manda para o Gemini (mesmo com acento).
    assert escolher_caminho("Compare com os outros livros", tem_livro_ativo=True) == GEMINI
    assert escolher_caminho("O que a Biblioteca diz sobre RAG?", tem_livro_ativo=True) == GEMINI
    assert escolher_caminho("Qual a diferença entre os autores?", tem_livro_ativo=True) == GEMINI
    # Sem livro na trilha, sempre Gemini.
    assert escolher_caminho("O que é RAG?", tem_livro_ativo=False) == GEMINI


def test_documentos_do_claude_tem_cache_no_fim():
    from estudo_ia.leitura.claude_livro import montar_documentos

    livro = Livro(titulo="Livro", autor="Autora", arquivo="l.pdf", formato="pdf")
    docs = montar_documentos(livro, [cap(1, 100, 1, 2), cap(2, 100, 3, 4)])
    assert [d["title"] for d in docs] == ["Cap. 1: Cap 1", "Cap. 2: Cap 2"]
    assert "cache_control" in docs[-1] and "cache_control" not in docs[0]
    assert all("citations" not in d for d in docs)  # citações desligadas (direitos autorais)


def test_rotulo_do_botao_de_livro():
    from estudo_ia.bot.teclados import rotulo_livro

    assert rotulo_livro("Inspired", ativo=False, progresso=None) == "Inspired"
    assert rotulo_livro("Inspired", ativo=True, progresso=(2, 7)) == "▶️ Inspired · 2/7"
    assert rotulo_livro("Inspired", ativo=False, progresso=(7, 7)) == "Inspired · ✅"
    longo = rotulo_livro("x" * 80, ativo=False, progresso=None)
    assert len(longo) == 48 and longo.endswith("…")


def test_teclado_marca_livro_ativo_e_progresso(tmp_path):
    from estudo_ia.bot.teclados import teclado_livros

    engine = criar_engine(tmp_path / "t.db")
    livro_id = criar_livro(engine)
    botoes = [linha[0] for linha in teclado_livros(engine).inline_keyboard]
    assert [b.text for b in botoes] == ["Cointeligência"]  # sem trilha ainda
    assert botoes[0].callback_data == f"livro:{livro_id}"

    planejador.escolher_livro(engine, livro_id)
    planejador.pular_proxima(engine)
    botoes = [linha[0] for linha in teclado_livros(engine).inline_keyboard]
    assert botoes[0].text == "▶️ Cointeligência · 1/2"


def test_texto_da_proxima_sessao(tmp_path):
    from estudo_ia.bot.app import texto_proxima_sessao

    assert "Escolha com /livros" in texto_proxima_sessao(None)
    engine = criar_engine(tmp_path / "t.db")
    planejador.escolher_livro(engine, criar_livro(engine))
    texto = texto_proxima_sessao(planejador.situacao_atual(engine))
    assert "Próxima sessão (1 de 2)" in texto and "Páginas 1–20" in texto
