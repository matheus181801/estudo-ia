"""Ajuda a montar mensagens para o Telegram.

O Gemini responde em Markdown (**negrito**, # títulos). O Telegram entende
um pedaço de HTML, então convertemos o básico. Também quebramos textos
longos, porque cada mensagem do Telegram aceita no máximo 4.096 caracteres.
"""

import html
import re
import unicodedata

LIMITE_TELEGRAM = 4096


def markdown_para_html(texto: str) -> str:
    texto = html.escape(texto)  # evita que <, > e & quebrem o HTML
    texto = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", texto, flags=re.MULTILINE)
    texto = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", texto)
    texto = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", texto)
    texto = re.sub(r"`([^`]+)`", r"<code>\1</code>", texto)
    texto = re.sub(r"^&gt;\s?", "▎ ", texto, flags=re.MULTILINE)  # citações
    texto = re.sub(r"^-{3,}$", "", texto, flags=re.MULTILINE)
    return texto.strip()


def dividir(texto: str, limite: int = LIMITE_TELEGRAM - 96) -> list[str]:
    """Quebra o texto em partes, de preferência entre parágrafos.

    A folga no limite deixa espaço para as tags HTML acrescentadas depois.
    """
    partes, atual = [], ""
    for paragrafo in texto.split("\n\n"):
        while len(paragrafo) > limite:  # parágrafo gigante: corta no tamanho
            if atual:
                partes.append(atual)
                atual = ""
            partes.append(paragrafo[:limite])
            paragrafo = paragrafo[limite:]
        candidato = f"{atual}\n\n{paragrafo}" if atual else paragrafo
        if len(candidato) > limite:
            partes.append(atual)
            atual = paragrafo
        else:
            atual = candidato
    if atual:
        partes.append(atual)
    return partes


def normalizar(texto: str) -> str:
    """Minúsculas e sem acentos, para comparar nomes de livros."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sem_acento.lower().strip()
