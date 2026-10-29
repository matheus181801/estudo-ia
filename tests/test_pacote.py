"""Testes da Fase 3: pacote diário (sem chamar a API: usamos um pacote de mentira)."""

import sqlite3
from datetime import date

from estudo_ia.db import Capitulo, Livro, Pacote as PacoteDB, Sessao, abrir_sessao, criar_engine
from estudo_ia.pacote.gerador import conferir_conteudo, escolher_revisao, texto_da_sessao
from estudo_ia.pacote.modelos import (ConteudoPacote, MidiaPacote, Pacote, QuestaoAberta,
                                      QuestaoMultipla, Secao, Slide, Termo)
from estudo_ia.pacote.renderizar import renderizar_html


def pacote_falso(prefixo: str = "Q") -> Pacote:
    conteudo = ConteudoPacote(
        titulo="Título <da> edição",
        abertura="Gancho **forte**.",
        secoes=[Secao(emoji="🧠", titulo="Seção", texto="Parágrafo 1.\n\nParágrafo 2.")],
        ideias_chave=[f"Ideia {i}" for i in range(5)],
        na_pratica="Aplique.",
        curiosidade="Curioso.",
        ingles=[Termo(termo=f"term{i}", traducao="t", explicacao="e", exemplo="ex") for i in range(5)],
        multipla_escolha=[
            QuestaoMultipla(enunciado=f"{prefixo}{i}?", alternativas=["a", "b", "c", "d"], correta=i % 4, comentario="c")
            for i in range(10)
        ],
        abertas=[QuestaoAberta(enunciado=f"Aberta {i}", resposta_esperada="r") for i in range(5)],
    )
    midia = MidiaPacote(roteiro_video=[Slide(titulo="s", topicos=["t"], narracao="n")], fonte_podcast="notas")
    return Pacote(livro="Livro", autor="Autora", sessao_ordem=2, sessao_total=7, capitulos=["Cap 1"],
                  data="2026-10-29", conteudo=conteudo, midia=midia)


def test_conferir_conteudo_aponta_problemas():
    p = pacote_falso()
    assert conferir_conteudo(p.conteudo) == []
    p.conteudo.abertas = p.conteudo.abertas[:3]
    p.conteudo.multipla_escolha[0].correta = 7
    problemas = conferir_conteudo(p.conteudo)
    assert any("abertas" in x for x in problemas) and any("questão 1" in x for x in problemas)


def test_html_do_email_e_do_pdf():
    p = pacote_falso()
    email = renderizar_html(p, "email.html.j2")
    assert "Título &lt;da&gt; edição" in email  # texto da IA não quebra o HTML
    assert "<b>forte</b>" in email and "29 de outubro de 2026" in email
    pdf = renderizar_html(p, "pdf.html.j2")
    assert "Gabarito comentado" in pdf
    assert "B) b" in pdf  # questão 1 tem correta=1 → letra B
    assert pdf.index("Múltipla escolha") < pdf.index("Gabarito comentado")


def criar_livro_com_sessao(engine) -> Sessao:
    with abrir_sessao(engine) as s:
        livro = Livro(titulo="L", autor="A", arquivo="l.pdf", formato="pdf")
        s.add(livro)
        s.flush()
        cap = Capitulo(livro_id=livro.id, ordem=1, titulo="Longo", pagina_inicio=1, pagina_fim=10,
                       texto="".join(str(i) * 100 for i in range(10)))  # 100 caracteres por "página"
        s.add(cap)
        s.flush()
        sessao = Sessao(livro_id=livro.id, ordem=2, capitulo_inicio_id=cap.id, capitulo_fim_id=cap.id,
                        pagina_inicio=6, pagina_fim=10)
        s.add(sessao)
        s.commit()
        s.refresh(sessao)
        return sessao


def test_texto_da_sessao_pega_so_a_parte_do_capitulo(tmp_path):
    engine = criar_engine(tmp_path / "t.db")
    sessao = criar_livro_com_sessao(engine)
    _, texto = texto_da_sessao(engine, sessao)
    corpo = texto.split("\n\n", 1)[1]
    assert corpo == "".join(str(i) * 100 for i in range(5, 10))  # páginas 6 a 10


def test_revisao_espacada_usa_pacotes_anteriores(tmp_path):
    engine = criar_engine(tmp_path / "t.db")
    sessao = criar_livro_com_sessao(engine)
    assert escolher_revisao(engine, sessao) == []  # primeira sessão: nada para revisar

    with abrir_sessao(engine) as s:
        for i in range(4):
            caminho = tmp_path / f"p{i}.json"
            caminho.write_text(pacote_falso(prefixo=f"P{i}-").model_dump_json(), encoding="utf-8")
            s.add(PacoteDB(sessao_id=100 + i, data=date.today(), caminho_json=str(caminho)))
        s.commit()
    revisao = escolher_revisao(engine, sessao)
    assert len(revisao) == 3
    assert len({q.enunciado.split("-")[0] for q in revisao}) == 3  # de 3 pacotes diferentes


def test_migracao_acrescenta_coluna_nova(tmp_path):
    banco = tmp_path / "antigo.db"
    con = sqlite3.connect(banco)
    con.execute("CREATE TABLE pacote (id INTEGER PRIMARY KEY, sessao_id INTEGER, data DATE)")
    con.execute("INSERT INTO pacote (sessao_id, data) VALUES (1, '2026-10-29')")
    con.commit()
    con.close()

    criar_engine(banco)  # deve criar as colunas que faltam sem apagar a linha
    con = sqlite3.connect(banco)
    colunas = {linha[1] for linha in con.execute("PRAGMA table_info(pacote)")}
    assert "caminho_json" in colunas and "status" in colunas
    assert con.execute("SELECT count(*) FROM pacote").fetchone()[0] == 1
