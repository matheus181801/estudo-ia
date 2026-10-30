"""Revisão acumulada de uma matéria do MBA (para provas e trabalhos).

A cada aula nova, a revisão é refeita com TODAS as aulas da matéria:
resumo do que já foi visto, glossário completo (do zero, para quem não é
de tecnologia) e um simulado que mistura aulas antigas e novas.
O mesmo gerador atende o /revisao do bot, sob demanda.
"""

from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from estudo_ia.config import Config
from estudo_ia.pacote.modelos import QuestaoAberta, QuestaoMultipla, TermoGlossario
from estudo_ia.pacote.renderizar import MESES, _ambiente

PEDIDO = """Você recebe as notas de todas as aulas já dadas da matéria "{materia}" do MBA em AI Leadership.
O Matheus está em transição de carreira e não é da área de tecnologia. Crie uma revisão para prova:
- um resumo acumulado por aula (o essencial de cada uma, em linguagem simples);
- as conexões entre as aulas (como os temas se ligam);
- um glossário completo da matéria, explicando cada termo do zero (10 a 25 termos);
- um simulado com 12 questões de múltipla escolha e 3 abertas, misturando TODAS as aulas,
  com cenários práticos e gabarito comentado; varie a posição da alternativa correta.
Use só o conteúdo das notas, com as suas palavras. Português do Brasil; termos técnicos em
inglês com a explicação ao lado. Tom leve, mas sem perder a profundidade."""


class ResumoAula(BaseModel):
    aula: str = Field(description="Ex.: 'Aula 1 — 22/10: o papel do CAIO'")
    essencial: str = Field(description="O essencial da aula, 1 a 3 parágrafos curtos")


class RevisaoMateria(BaseModel):
    resumos: list[ResumoAula]
    conexoes: str = Field(description="Como os temas das aulas se ligam (1 a 2 parágrafos)")
    glossario: list[TermoGlossario]
    multipla_escolha: list[QuestaoMultipla] = Field(description="Exatamente 12 questões")
    abertas: list[QuestaoAberta] = Field(description="Exatamente 3 questões")


def gerar_revisao(cliente, config: Config, materia: str, notas_por_aula: list[tuple[str, str]]) -> RevisaoMateria:
    """notas_por_aula: [(rótulo da aula, notas em texto)] em ordem cronológica."""
    documentos = [
        {"type": "document", "title": rotulo,
         "source": {"type": "text", "media_type": "text/plain", "data": texto}}
        for rotulo, texto in notas_por_aula
    ]
    try:
        with cliente.messages.stream(
            model=config.claude_modelo, max_tokens=64000,
            messages=[{"role": "user", "content": documentos
                       + [{"type": "text", "text": PEDIDO.format(materia=materia)}]}],
            output_format=RevisaoMateria,
        ) as stream:
            resposta = stream.get_final_message()
    except ValidationError as erro:
        raise RuntimeError("A revisão veio incompleta (JSON cortado).") from erro
    if resposta.stop_reason in ("max_tokens", "refusal"):
        raise RuntimeError(f"Não consegui gerar a revisão ({resposta.stop_reason}).")
    return resposta.parsed_output


def gerar_pdf_revisao(revisao: RevisaoMateria, materia: str, total_aulas: int, destino: Path) -> Path:
    from playwright.sync_api import sync_playwright

    hoje = date.today()
    html = _ambiente().get_template("revisao.html.j2").render(
        r=revisao, materia=materia, total_aulas=total_aulas,
        data_br=f"{hoje.day} de {MESES[hoje.month - 1]} de {hoje.year}",
    )
    destino.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        navegador = pw.chromium.launch()
        pagina = navegador.new_page()
        pagina.set_content(html, wait_until="load")
        pagina.pdf(path=str(destino), prefer_css_page_size=True, print_background=True)
        navegador.close()
    return destino
