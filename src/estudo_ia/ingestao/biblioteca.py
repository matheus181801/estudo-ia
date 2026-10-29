"""Leva os livros da pasta `biblioteca/` para o banco SQLite."""

from dataclasses import dataclass, field
from pathlib import Path

from sqlmodel import func, select

from estudo_ia.db import Capitulo, Livro, abrir_sessao
from estudo_ia.ingestao.extracao import FORMATOS_ACEITOS, extrair_livro


@dataclass
class ResultadoIngestao:
    novos: list[str] = field(default_factory=list)
    ja_existiam: int = 0
    avisos: list[str] = field(default_factory=list)


def ingerir_pasta(engine, pasta: Path) -> ResultadoIngestao:
    """Processa só os livros que ainda não estão no banco."""
    resultado = ResultadoIngestao()
    arquivos = sorted(p for p in Path(pasta).iterdir() if p.suffix.lower() in FORMATOS_ACEITOS)

    with abrir_sessao(engine) as s:
        conhecidos = set(s.exec(select(Livro.arquivo)).all())

        for arquivo in arquivos:
            if arquivo.name in conhecidos:
                resultado.ja_existiam += 1
                continue

            try:
                extraido = extrair_livro(arquivo)
            except Exception as erro:  # arquivo corrompido, protegido por DRM etc.
                resultado.avisos.append(f"{arquivo.name}: não consegui abrir ({erro}).")
                continue

            resultado.avisos += [f"{arquivo.name}: {a}" for a in extraido.avisos]
            if not extraido.capitulos:
                continue

            livro = Livro(
                titulo=extraido.titulo,
                autor=extraido.autor,
                arquivo=arquivo.name,
                formato=extraido.formato,
                total_paginas=extraido.total_paginas,
            )
            s.add(livro)
            s.flush()  # gera o livro.id para usar nos capítulos
            for cap in extraido.capitulos:
                s.add(Capitulo(
                    livro_id=livro.id,
                    ordem=cap.ordem,
                    titulo=cap.titulo,
                    pagina_inicio=cap.pagina_inicio,
                    pagina_fim=cap.pagina_fim,
                    texto=cap.texto,
                ))
            s.commit()  # um commit por livro: se algo falhar, os anteriores ficam salvos
            resultado.novos.append(f"{livro.titulo} ({len(extraido.capitulos)} capítulos)")

    return resultado


def listar_livros(engine) -> list[tuple[Livro, int, int]]:
    """Devolve (livro, nº de capítulos, nº de capítulos já no File Search)."""
    with abrir_sessao(engine) as s:
        consulta = (
            select(Livro, func.count(Capitulo.id), func.count(Capitulo.file_search_doc))
            .join(Capitulo)
            .group_by(Livro.id)
            .order_by(Livro.titulo)
        )
        return list(s.exec(consulta).all())
