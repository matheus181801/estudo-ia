"""Reconhece as aulas no Drive e extrai o texto do material e da transcrição.

Padrão das pastas: "DD.MM.AAAA - Matéria" (ex.: "29.10.2026 - Estratégia de IA").
Regras combinadas com o Matheus:
- "Pré Aula" é ignorada;
- "Aula 1 - Encontro com a coordenação" vai para a matéria "Geral";
- só entram o MATERIAL da aula (PDF) e a TRANSCRIÇÃO do Teams (DOCX).
  Exercícios, gabaritos, planilhas, anotações e estudos antigos ficam de fora.
"""

import io
import re
from dataclasses import dataclass
from datetime import date

import docx
import pymupdf

from estudo_ia.mba.drive import ArquivoDrive

MATERIA_GERAL = "Geral"
PADRAO_PASTA = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})\s*-\s*(.+?)\s*$")

# Palavras que indicam arquivo que NÃO é material nem transcrição.
FORA = ("exercicio", "exercício", "gabarito", "respondido", "rascunho", "anotações", "anotacoes",
        "estudo -", "estudo-", "mapa mental", "caderno", "painel")


@dataclass
class AulaIdentificada:
    data: date
    materia: str
    titulo: str  # nome da pasta, como está no Drive


def identificar_aula(nome_pasta: str) -> AulaIdentificada | None:
    """Lê data e matéria do nome da pasta. Devolve None se a pasta deve ser ignorada."""
    casamento = PADRAO_PASTA.match(nome_pasta)
    if not casamento:
        return None
    dia, mes, ano, resto = casamento.groups()
    ano = int(ano) + 2000 if len(ano) == 2 else int(ano)
    if re.search(r"pr[ée][\s-]*aula", resto, re.IGNORECASE):
        return None
    if re.search(r"coordena", resto, re.IGNORECASE):
        materia = MATERIA_GERAL
    else:
        # "Aula 2 - AI Core Concepts" → "AI Core Concepts"
        materia = re.sub(r"^aula\s*\d+\s*-\s*", "", resto, flags=re.IGNORECASE).strip()
    return AulaIdentificada(date(ano, int(mes), int(dia)), materia, nome_pasta.strip())


def _fora(nome: str) -> bool:
    nome = nome.lower()
    return any(palavra in nome for palavra in FORA)


def escolher_arquivos(arquivos: list[ArquivoDrive]) -> tuple[list[ArquivoDrive], list[ArquivoDrive]]:
    """Separa (materiais em PDF, transcrições em DOCX)."""
    materiais = [a for a in arquivos if a.nome.lower().endswith(".pdf") and not _fora(a.nome)]
    transcricoes = [a for a in arquivos if a.nome.lower().endswith(".docx") and not _fora(a.nome)
                    and re.search(r"transcri|reuni", a.nome, re.IGNORECASE)]
    return materiais, transcricoes


def texto_pdf(conteudo: bytes) -> str:
    with pymupdf.open(stream=conteudo, filetype="pdf") as doc:
        paginas = [f"[Slide {i}]\n{p.get_text().strip()}" for i, p in enumerate(doc, 1)]
    return "\n\n".join(p for p in paginas if p.strip().split("\n", 1)[-1])


def texto_docx(conteudo: bytes) -> str:
    documento = docx.Document(io.BytesIO(conteudo))
    return "\n".join(p.text for p in documento.paragraphs if p.text.strip())


# Cabeçalho de fala no Teams: "Nome Sobrenome   1:23" ou "Nome   1:02:03".
CABECALHO_FALA = re.compile(r"^(?P<nome>[^\d\n]{3,80}?)\s+(?P<tempo>\d{1,2}:\d{2}(?::\d{2})?)\s*$")


def anonimizar_transcricao(texto: str) -> tuple[str, str]:
    """Compacta a transcrição e troca o nome dos colegas por "Aluno".

    O professor é quem mais fala. Os nomes dos colegas não saem daqui:
    nem a IA recebe (privacidade combinada com o Matheus).
    Devolve (nome do professor, transcrição no formato "Professor: ..."/"Aluno: ...").
    """
    falas: list[tuple[str, list[str]]] = []
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha or "começou a transcrição" in linha or "parou a transcrição" in linha:
            continue
        cabecalho = CABECALHO_FALA.match(linha)
        if cabecalho:
            falas.append((cabecalho["nome"].strip(), []))
        elif falas:
            falas[-1][1].append(linha)

    palavras: dict[str, int] = {}
    for nome, linhas in falas:
        palavras[nome] = palavras.get(nome, 0) + sum(len(l.split()) for l in linhas)
    if not palavras:
        return "", texto
    professor = max(palavras, key=palavras.get)

    saida = []
    for nome, linhas in falas:
        if not linhas:
            continue
        quem = "Professor" if nome == professor else "Aluno"
        fala = " ".join(linhas)
        # Junta falas seguidas da mesma pessoa (o Teams quebra muito).
        if saida and saida[-1].startswith(quem + ":"):
            saida[-1] += " " + fala
        else:
            saida.append(f"{quem}: {fala}")
    return professor, "\n".join(saida)
