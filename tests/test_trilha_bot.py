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
