"""Testes da Fase 1: extração de capítulos e ingestão no banco.

Os livros de verdade não vão para o git, então cada teste cria um PDF
pequeno de mentira com o próprio PyMuPDF.
"""

import pymupdf

from estudo_ia.db import criar_engine
from estudo_ia.ingestao.biblioteca import ingerir_pasta, listar_livros
from estudo_ia.ingestao.extracao import extrair_livro

TEXTO = "Este é um parágrafo de teste sobre inteligência artificial. " * 20


def criar_pdf(caminho, paginas: int, sumario: list, texto: str = TEXTO, titulo: str = ""):
    doc = pymupdf.open()
    for i in range(paginas):
        pagina = doc.new_page()
        pagina.insert_textbox(pymupdf.Rect(50, 50, 550, 800), f"Página {i + 1}. {texto}")
    doc.set_toc(sumario)
    if titulo:
        doc.set_metadata({"title": titulo})
    doc.save(caminho)


def test_divide_pelo_sumario(tmp_path):
    arquivo = tmp_path / "Livro Teste - Fulana de Tal.pdf"
    criar_pdf(arquivo, 9, [
        [1, "Copyright", 1], [1, "Cap 1", 2], [1, "Cap 2", 4], [1, "Cap 3", 6],
        [1, "Cap 4", 7], [1, "Cap 5", 8], [1, "Index", 9],
    ])
    livro = extrair_livro(arquivo)
    assert livro.titulo == "Livro Teste"  # veio do nome do arquivo
    assert livro.autor == "Fulana de Tal"
    # Copyright e Index ficam de fora.
    assert [c.titulo for c in livro.capitulos] == ["Cap 1", "Cap 2", "Cap 3", "Cap 4", "Cap 5"]
    assert (livro.capitulos[0].pagina_inicio, livro.capitulos[0].pagina_fim) == (2, 3)


def test_parte_vira_capitulos(tmp_path):
    arquivo = tmp_path / "Partes.pdf"
    criar_pdf(arquivo, 6, [
        [1, "Parte I", 1], [2, "1. Primeiro", 2], [2, "2. Segundo", 4],
        [1, "Parte II", 5], [2, "3. Terceiro", 6],
    ])
    titulos = [c.titulo for c in extrair_livro(arquivo).capitulos]
    assert "1. Primeiro" in titulos and "3. Terceiro" in titulos


def test_titulo_dos_metadados_sem_for_fulano(tmp_path):
    arquivo = tmp_path / "x.pdf"
    criar_pdf(arquivo, 2, [[1, "Cap", 1]], titulo="Meu Livro (for Alguém)")
    assert extrair_livro(arquivo).titulo == "Meu Livro"


def test_pdf_escaneado_gera_aviso(tmp_path):
    arquivo = tmp_path / "Escaneado.pdf"
    criar_pdf(arquivo, 3, [[1, "Cap", 1]], texto="")
    livro = extrair_livro(arquivo)
    assert livro.capitulos == []
    assert any("escaneado" in a for a in livro.avisos)


def test_ingestao_so_processa_livros_novos(tmp_path):
    pasta = tmp_path / "biblioteca"
    pasta.mkdir()
    criar_pdf(pasta / "Um - Autor.pdf", 3, [[1, "A", 1], [1, "B", 2]])
    (pasta / "LEIA-ME.md").write_text("não é livro")
    engine = criar_engine(tmp_path / "teste.db")

    primeira = ingerir_pasta(engine, pasta)
    assert len(primeira.novos) == 1

    criar_pdf(pasta / "Dois - Autor.pdf", 2, [[1, "C", 1]])
    segunda = ingerir_pasta(engine, pasta)
    assert len(segunda.novos) == 1 and segunda.ja_existiam == 1

    livros = listar_livros(engine)
    assert [(l.titulo, caps) for l, caps, _ in livros] == [("Dois", 1), ("Um", 2)]
