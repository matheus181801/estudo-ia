"""Transforma o pacote (JSON) em HTML do e-mail e em PDF.

Templates jinja2: arquivos HTML com "buracos" ({{ ... }}) que o jinja2
preenche com os dados do pacote. O PDF é gerado abrindo o HTML num
navegador sem janela (Chromium, via Playwright) e mandando "imprimir em PDF".
"""

from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from estudo_ia.bot.formatacao import markdown_para_html
from estudo_ia.pacote.modelos import Pacote

PASTA_TEMPLATES = Path(__file__).parent / "templates"
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _paragrafos(texto: str) -> Markup:
    """Texto com linhas em branco vira <p>...</p>; **negrito** vira <b>."""
    blocos = [b.strip() for b in texto.split("\n\n") if b.strip()]
    return Markup("".join(f"<p>{markdown_para_html(b).replace(chr(10), '<br>')}</p>" for b in blocos))


def _inline(texto: str) -> Markup:
    """Para textos curtos (itens de lista, alternativas): só a formatação básica."""
    return Markup(markdown_para_html(texto))


def _ambiente() -> Environment:
    # autoescape: qualquer "<" vindo do texto vira "&lt;" e não quebra o HTML.
    env = Environment(loader=FileSystemLoader(PASTA_TEMPLATES), autoescape=select_autoescape(["j2"]))
    env.filters["paragrafos"] = _paragrafos
    env.filters["inline"] = _inline
    return env


def _data_br(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def renderizar_html(pacote: Pacote, template: str) -> str:
    return _ambiente().get_template(template).render(p=pacote, c=pacote.conteudo, data_br=_data_br(pacote.data))


def gerar_arquivos(pacote: Pacote, pasta: Path) -> tuple[Path, Path]:
    """Salva newsletter.html (corpo do e-mail) e pacote.pdf na pasta."""
    from playwright.sync_api import sync_playwright

    pasta.mkdir(parents=True, exist_ok=True)
    caminho_html = pasta / "newsletter.html"
    caminho_html.write_text(renderizar_html(pacote, "email.html.j2"), encoding="utf-8")

    caminho_pdf = pasta / "pacote.pdf"
    with sync_playwright() as pw:
        navegador = pw.chromium.launch()
        pagina = navegador.new_page()
        pagina.set_content(renderizar_html(pacote, "pdf.html.j2"), wait_until="load")
        pagina.pdf(path=str(caminho_pdf), prefer_css_page_size=True, print_background=True)
        navegador.close()
    return caminho_html, caminho_pdf
