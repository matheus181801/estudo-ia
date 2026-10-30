"""Transforma o roteiro do vídeo em imagens PNG (uma por slide).

Cada slide é uma página HTML de 1280×720 (tamanho de um quadro 720p). O
Playwright abre essa página num Chromium sem janela e tira um "print".
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from estudo_ia.pacote.modelos import Pacote

PASTA_TEMPLATES = Path(__file__).parent / "templates"
LARGURA, ALTURA = 1280, 720


def renderizar_slides_html(pacote: Pacote) -> list[str]:
    env = Environment(loader=FileSystemLoader(PASTA_TEMPLATES), autoescape=select_autoescape(["j2"]))
    template = env.get_template("slide.html.j2")
    slides = pacote.midia.roteiro_video
    return [
        template.render(
            s=slide, numero=i, total=len(slides), capa=(i == 1),
            livro=pacote.livro, autor=pacote.autor, sessao=pacote.sessao_ordem,
        )
        for i, slide in enumerate(slides, 1)
    ]


def gerar_pngs(pacote: Pacote, pasta: Path) -> list[Path]:
    from playwright.sync_api import sync_playwright

    pasta.mkdir(parents=True, exist_ok=True)
    caminhos = []
    with sync_playwright() as pw:
        navegador = pw.chromium.launch()
        pagina = navegador.new_page(viewport={"width": LARGURA, "height": ALTURA})
        for i, html in enumerate(renderizar_slides_html(pacote), 1):
            pagina.set_content(html, wait_until="load")
            caminho = pasta / f"slide{i:02}.png"
            pagina.screenshot(path=str(caminho))
            caminhos.append(caminho)
        navegador.close()
    return caminhos
