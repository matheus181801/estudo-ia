"""Testes do MBA: leitura das aulas, anonimização, conexões com livros e template."""

from datetime import date

from estudo_ia.mba.aulas import (MATERIA_GERAL, anonimizar_transcricao, escolher_arquivos,
                                 identificar_aula)
from estudo_ia.mba.drive import ArquivoDrive
from estudo_ia.mba.pacote import conferir_conexoes
from estudo_ia.pacote.modelos import ConexaoLivro, TermoGlossario
from estudo_ia.pacote.renderizar import renderizar_html
from tests.test_pacote import pacote_falso


def test_identificar_aula_pelo_nome_da_pasta():
    a = identificar_aula("29.10.2026 - Estratégia de IA")
    assert (a.data, a.materia) == (date(2026, 10, 29), "Estratégia de IA")
    assert identificar_aula("27.10.2026 - Aula 2 - AI Core Concepts").materia == "AI Core Concepts"
    assert identificar_aula("13.10.26 - Aula 1 - Encontro com a coordenação").materia == MATERIA_GERAL
    assert identificar_aula("13.10.26 - Aula 1 - Encontro com a coordenação").data == date(2026, 10, 13)
    assert identificar_aula("13.10.26 - Pré Aula - Advanced Skills") is None  # ignorada
    assert identificar_aula("Materiais Complementares") is None  # fora do padrão


def test_escolher_so_material_e_transcricao():
    def arq(nome):
        return ArquivoDrive(id=nome, nome=nome, tipo="", tamanho=1)

    arquivos = [arq(n) for n in [
        "Aula 01 de 05 - Prof Igor.pdf", "Reunião em _Estratégia de IA_ 22.10.docx",
        "EXERCICIO 3 - SpeakUp.pdf", "Gabarito_Exercicio_01.docx", "Respondido - EXERCICIO 2.docx",
        "Anotações Matheus - Aula 1.docx", "Estudo - Aula 01.pdf", "metrica.csv", "Correlação.xlsx",
        "Transcrição - Aula 1 - Reunião em _AI Core Concepts_.docx", "Caderno de Hipóteses.docx",
    ]]
    materiais, transcricoes = escolher_arquivos(arquivos)
    assert [m.nome for m in materiais] == ["Aula 01 de 05 - Prof Igor.pdf"]
    assert [t.nome for t in transcricoes] == ["Reunião em _Estratégia de IA_ 22.10.docx",
                                              "Transcrição - Aula 1 - Reunião em _AI Core Concepts_.docx"]


def test_anonimizar_troca_nomes_e_acha_o_professor():
    bruto = "\n".join([
        "Reunião em Estratégia de IA-20261022", "Igor Professor Silva começou a transcrição",
        "Igor Professor Silva   0:04", "Hoje vamos falar de estratégia de IA e do papel do CAIO.",
        "Maria Aluna Souza   1:10", "Professor, o CAIO responde ao CEO?",
        "Igor Professor Silva   1:20", "Depende da maturidade da empresa,", "mas o ideal é responder ao CEO.",
        "João Colega   1:02:03", "Kkkk boa",
    ])
    professor, texto = anonimizar_transcricao(bruto)
    assert professor == "Igor Professor Silva"
    assert texto.splitlines() == [
        "Professor: Hoje vamos falar de estratégia de IA e do papel do CAIO.",
        "Aluno: Professor, o CAIO responde ao CEO?",
        "Professor: Depende da maturidade da empresa, mas o ideal é responder ao CEO.",
        "Aluno: Kkkk boa",
    ]
    assert "Maria" not in texto and "João" not in texto


def test_conexoes_inventadas_sao_descartadas():
    sumario = [("Cointeligência", "Cap. 4: Quatro regras"), ("LLMOps", "Cap. 1: Introdução")]
    conexoes = [
        ConexaoLivro(livro="Cointeligência", capitulo="Cap. 4: Quatro regras", por_que_ler="x"),
        ConexaoLivro(livro="Livro Inventado", capitulo="Cap. 9: Nada", por_que_ler="y"),
        ConexaoLivro(livro="llmops ", capitulo="cap. 1: introdução", por_que_ler="z"),  # maiúsculas/espaço
    ]
    assert [c.livro for c in conferir_conexoes(conexoes, sumario)] == ["Cointeligência", "llmops "]


def test_template_da_aula_tem_secoes_do_mba():
    p = pacote_falso()
    p.tipo, p.livro, p.autor, p.sessao_ordem, p.capitulos = "aula", "Estratégia de IA", "Igor", 2, ["O papel do CAIO"]
    p.glossario = [TermoGlossario(termo="Prompt", explicacao="O pedido que você faz para a IA.")]
    p.conexoes_livros = [ConexaoLivro(livro="Cointeligência", capitulo="Cap. 4", por_que_ler="Regras de uso.")]
    p.avisos = ["Dinâmica final vale 10 pontos."]
    for template in ("email.html.j2", "pdf.html.j2"):
        html = renderizar_html(p, template)
        assert "MBA · Estratégia de IA · Aula 2" in html and "Prof. Igor" in html
        assert "Glossário para iniciantes" in html and "Nos seus livros" in html and "Avisos da aula" in html
        assert "Sessão 2 de" not in html  # cabeçalho de livro não aparece


def test_template_do_livro_nao_muda():
    html = renderizar_html(pacote_falso(), "email.html.j2")
    assert "Sessão 2 de 7" in html
    assert "Glossário para iniciantes" not in html and "Avisos da aula" not in html
