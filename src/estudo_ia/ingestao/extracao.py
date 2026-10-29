"""Extração de livros (PDF e EPUB) em capítulos.

Usamos o PyMuPDF para os dois formatos: ele abre PDF e EPUB do mesmo jeito,
com `get_toc()` (o sumário) e o texto de cada página. Assim temos um só
caminho de código, em vez de uma biblioteca para cada formato.

Este módulo não fala com banco nem com internet: recebe um arquivo e
devolve dados. Isso facilita testar.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

FORMATOS_ACEITOS = {".pdf", ".epub"}
LIMITE_MB = 100  # limite de arquivo do Gemini File Search
MIN_CHARS_POR_PAGINA = 100  # abaixo disso, o PDF provavelmente é escaneado
MIN_CHARS_CAPITULO = 500  # capítulos menores (capa, copyright) são ignorados
PAGINAS_CAPITULO_GRANDE = 60  # "capítulos" maiores que isso são divididos pelos subitens

# Partes do livro que não são conteúdo de estudo e só atrapalhariam a busca.
TITULOS_IGNORADOS = {
    "index", "índice", "indice", "índice remissivo", "notes", "notas", "about the author",
    "about the authors", "sobre o autor", "sobre os autores", "credits", "créditos",
    "copyright", "copyright page", "página de direitos autorais", "direitos autorais", "contents", "table of contents", "sumário", "acknowledgments",
    "acknowledgements", "agradecimentos", "dedicatória", "dedication", "also by",
    "capa", "cover", "folha de rosto", "title page", "mídias sociais",
}

# Autores "lixo" que alguns arquivos trazem nos metadados.
AUTORES_INVALIDOS = {"author names here", "welcome.html", "unknown", "desconhecido"}

pymupdf.TOOLS.mupdf_display_errors(False)  # silencia avisos internos do MuPDF


@dataclass
class CapituloExtraido:
    ordem: int
    titulo: str
    pagina_inicio: int  # 1 = primeira página
    pagina_fim: int
    texto: str


@dataclass
class LivroExtraido:
    titulo: str
    autor: str
    formato: str
    total_paginas: int
    capitulos: list[CapituloExtraido] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def _titulo_e_autor(caminho: Path, metadados: dict) -> tuple[str, str]:
    """Usa os metadados do arquivo e, se estiverem ruins, o nome do arquivo.

    Os nomes dos arquivos seguem o padrão "Título - Autor".
    """
    partes = caminho.stem.split(" - ", 1)
    titulo_arquivo = partes[0].replace("_", ":").strip()
    autor_arquivo = partes[1].strip() if len(partes) > 1 else ""

    titulo = (metadados.get("title") or "").strip()
    # Alguns e-books gratuitos trazem "(for Fulano)" no título; tiramos isso.
    titulo = re.sub(r"\s*\(for [^)]*\)\s*$", "", titulo)
    if not titulo:
        titulo = titulo_arquivo

    autor = (metadados.get("author") or "").strip().rstrip(";")
    if not autor or autor.lower() in AUTORES_INVALIDOS:
        autor = autor_arquivo
    return titulo, autor


def _escolher_nivel(sumario: list) -> int:
    """Escolhe o nível do sumário que representa os capítulos.

    Em geral é o nível 1. Mas alguns livros usam o nível 1 só para "Partes"
    (2 ou 3 itens); nesse caso descemos para o nível 2.
    """
    contagem = {}
    for nivel, *_ in sumario:
        contagem[nivel] = contagem.get(nivel, 0) + 1
    if contagem.get(1, 0) < 5 and contagem.get(2, 0) >= 5:
        return 2
    return 1


def _marcos_do_sumario(sumario: list, total_paginas: int) -> list[tuple[str, int]]:
    """Transforma o sumário numa lista de (título, página inicial) dos capítulos.

    Se um item for grande demais (ex.: "Parte II" com 90 páginas), também
    entram os subitens dele, para os capítulos ficarem de tamanho estudável.
    """
    nivel = _escolher_nivel(sumario)
    itens = [(n, t.strip(), p) for n, t, p, *_ in sumario if p > 0]
    marcos = []
    for i, (n, titulo, pagina) in enumerate(itens):
        if n != nivel:
            continue
        marcos.append((titulo, pagina))
        # Subitens vão até o próximo item do mesmo nível (ou mais alto).
        filhos = []
        fim = total_paginas + 1
        for n2, titulo2, pagina2 in itens[i + 1 :]:
            if n2 <= nivel:
                fim = pagina2
                break
            if n2 == nivel + 1:
                filhos.append((titulo2, pagina2))
        e_parte = re.match(r"(parte|part)\b", titulo, re.IGNORECASE)
        if e_parte:
            marcos += filhos  # "Parte I" não ajuda na citação; o subitem já é o capítulo
        elif fim - pagina > PAGINAS_CAPITULO_GRANDE:
            # Seções de um capítulo grande levam o nome do capítulo junto.
            marcos += [(f"{titulo} › {t}", p) for t, p in filhos]
    return marcos


def _completar_titulo(titulo: str, texto: str) -> str:
    """Se o sumário só diz "Chapter 1:", usa a linha seguinte do texto como título."""
    if not titulo.endswith(":"):
        return titulo
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    if len(linhas) < 2 or linhas[0] != titulo:
        return titulo
    # O título pode estar quebrado em várias linhas em CAIXA ALTA.
    partes = []
    for linha in linhas[1:4]:
        if partes and not linha.isupper():
            break
        partes.append(linha)
        if not linha.isupper():
            break
    complemento = " ".join(partes)
    return f"{titulo} {complemento.capitalize() if complemento.isupper() else complemento}"


def _limpar_texto(texto: str) -> str:
    texto = texto.replace("­", "")  # hífen invisível
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def extrair_livro(caminho: Path) -> LivroExtraido:
    """Abre o livro e devolve título, autor e a lista de capítulos com texto."""
    caminho = Path(caminho)
    formato = caminho.suffix.lower().lstrip(".")
    doc = pymupdf.open(caminho)
    titulo, autor = _titulo_e_autor(caminho, doc.metadata or {})
    livro = LivroExtraido(titulo=titulo, autor=autor, formato=formato, total_paginas=doc.page_count)

    tamanho_mb = caminho.stat().st_size / 1024 / 1024
    if tamanho_mb > LIMITE_MB:
        livro.avisos.append(f"Arquivo com {tamanho_mb:.0f} MB (acima de {LIMITE_MB} MB).")

    paginas = [_limpar_texto(pagina.get_text()) for pagina in doc]

    media = sum(len(p) for p in paginas) / max(1, len(paginas))
    if media < MIN_CHARS_POR_PAGINA:
        livro.avisos.append("Quase sem texto selecionável: parece um PDF escaneado. Livro ignorado.")
        return livro

    # Monta a lista (título, página inicial) dos capítulos a partir do sumário.
    sumario = doc.get_toc()
    if sumario:
        marcos = _marcos_do_sumario(sumario, doc.page_count)
    else:
        livro.avisos.append("Livro sem sumário: dividido em blocos de 20 páginas.")
        marcos = [(f"Parte {i // 20 + 1}", i + 1) for i in range(0, doc.page_count, 20)]

    # Cada capítulo vai da sua página inicial até a véspera do próximo.
    # Se dois itens começam na mesma página, fica só o primeiro.
    marcos.sort(key=lambda m: m[1])
    marcos = [m for i, m in enumerate(marcos) if i == 0 or m[1] != marcos[i - 1][1]]
    ordem = 0
    for i, (titulo_cap, inicio) in enumerate(marcos):
        fim = marcos[i + 1][1] - 1 if i + 1 < len(marcos) else doc.page_count
        fim = max(fim, inicio)
        texto = "\n\n".join(paginas[inicio - 1 : fim])
        if len(texto) < MIN_CHARS_CAPITULO or titulo_cap.lower() in TITULOS_IGNORADOS:
            continue
        titulo_cap = _completar_titulo(titulo_cap, texto)
        ordem += 1
        livro.capitulos.append(CapituloExtraido(ordem, titulo_cap, inicio, fim, texto))

    return livro
