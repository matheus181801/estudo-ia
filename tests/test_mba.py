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


# ---------------------------------------------------------------- processador

from datetime import datetime  # noqa: E402

from estudo_ia.config import Config  # noqa: E402
from estudo_ia.db import AulaMBA, Materia, abrir_sessao, criar_engine  # noqa: E402
from estudo_ia.mba import processador  # noqa: E402
from estudo_ia.mba.drive import PastaAula  # noqa: E402
from sqlmodel import select  # noqa: E402


def test_entrega_as_6h30_do_dia_seguinte():
    aula = AulaMBA(pasta_id="x", titulo="t", data=date(2026, 10, 29), materia_id=1)
    config = Config(hora_entrega_mba="06:30")
    assert not processador.hora_de_entregar(aula, config, datetime(2026, 10, 29, 23, 0))
    assert not processador.hora_de_entregar(aula, config, datetime(2026, 10, 30, 6, 29))
    assert processador.hora_de_entregar(aula, config, datetime(2026, 10, 30, 6, 30))


def test_retoma_pela_ultima_etapa_com_arquivo(tmp_path):
    assert processador.etapa_pelos_arquivos(tmp_path) == "nova"
    (tmp_path / "notas.json").write_text("{}")
    assert processador.etapa_pelos_arquivos(tmp_path) == "notas"
    (tmp_path / "pacote.pdf").write_bytes(b"%PDF")
    assert processador.etapa_pelos_arquivos(tmp_path) == "pacote"


def test_slug_sem_acentos():
    assert processador.slug("22.10.2026 - Estratégia de IA") == "22.10.2026-Estrategia-de-IA"


class PonteFalsa:
    """Imita a Ponte Drive: uma aula nova e uma já processada (com notas e estado no Drive)."""

    def __init__(self):
        self.arquivos = {"n1": b'{"titulo_aula": "x"}', "e1": b'{"entregue": true, "topico_id": 42, "professor": "Igor"}'}

    def listar_aulas(self):
        return [PastaAula(id="p1", nome="22.10.2026 - Estratégia de IA", criada=""),
                PastaAula(id="p2", nome="29.10.2026 - Estratégia de IA", criada=""),
                PastaAula(id="p3", nome="13.10.26 - Pré Aula - Algo", criada="")]

    def listar_processadas(self):
        feita = PastaAula(id="d1", nome="22.10.2026 - Estratégia de IA", criada="", arquivos=[
            ArquivoDrive(id="n1", nome="notas.json", tipo="", tamanho=1),
            ArquivoDrive(id="e1", nome="estado.json", tipo="", tamanho=1)])
        return {"Estratégia de IA": [feita]}

    def baixar(self, arquivo_id):
        return self.arquivos[arquivo_id]


def test_sincronizar_importa_processadas_e_registra_novas(tmp_path):
    engine = criar_engine(tmp_path / "t.db")
    novas = processador.sincronizar(engine, Config(data_dir=tmp_path), PonteFalsa(), avisar=lambda *_: None)
    assert novas == ["29.10.2026 - Estratégia de IA"]  # a Pré Aula é ignorada
    with abrir_sessao(engine) as s:
        etapas = {a.titulo: a.etapa for a in s.exec(select(AulaMBA)).all()}
        materia = s.exec(select(Materia)).one()
    assert etapas == {"22.10.2026 - Estratégia de IA": "entregue", "29.10.2026 - Estratégia de IA": "nova"}
    assert materia.topico_id == 42  # tópico recuperado do Drive: não cria tópico duplicado
    # Rodar de novo não duplica nada.
    assert processador.sincronizar(engine, Config(data_dir=tmp_path), PonteFalsa(), avisar=lambda *_: None) == []
