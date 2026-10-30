"""Planejador da trilha: divide um livro em sessões de ~90 minutos.

Medimos o tamanho pela quantidade de caracteres, e não pelas páginas,
porque uma "página" de EPUB e uma de PDF têm tamanhos bem diferentes.
Uma página de livro tem uns 2.000 caracteres; 25 páginas ≈ 50.000.
"""

import math
from dataclasses import dataclass

from sqlmodel import select

from estudo_ia.db import Capitulo, Livro, Progresso, Sessao, abrir_sessao

ALVO_CHARS = 50_000  # ~25 páginas
MIN_CHARS = 30_000  # ~15 páginas
MAX_CHARS = 60_000  # ~30 páginas


@dataclass
class SessaoPlanejada:
    capitulos: list[Capitulo]
    pagina_inicio: int
    pagina_fim: int
    caracteres: int


def planejar(capitulos: list[Capitulo]) -> list[SessaoPlanejada]:
    """Agrupa capítulos curtos e divide capítulos longos em sessões."""
    sessoes: list[SessaoPlanejada] = []
    atual: SessaoPlanejada | None = None

    for cap in sorted(capitulos, key=lambda c: c.ordem):
        tamanho = len(cap.texto)

        if tamanho > MAX_CHARS:
            # Capítulo longo: fecha a sessão em andamento e divide este em partes iguais.
            if atual:
                sessoes.append(atual)
                atual = None
            partes = math.ceil(tamanho / ALVO_CHARS)
            paginas = cap.pagina_fim - cap.pagina_inicio + 1
            for i in range(partes):
                inicio = cap.pagina_inicio + (paginas * i) // partes
                fim = cap.pagina_inicio + (paginas * (i + 1)) // partes - 1
                sessoes.append(SessaoPlanejada([cap], inicio, max(inicio, fim), tamanho // partes))
            continue

        # Capítulo curto: junta com o anterior, desde que não estoure o máximo.
        if atual and atual.caracteres + tamanho > MAX_CHARS and atual.caracteres >= MIN_CHARS:
            sessoes.append(atual)
            atual = None
        if atual is None:
            atual = SessaoPlanejada([], cap.pagina_inicio, cap.pagina_fim, 0)
        atual.capitulos.append(cap)
        atual.pagina_fim = cap.pagina_fim
        atual.caracteres += tamanho

    if atual:
        sessoes.append(atual)
    return sessoes


def escolher_livro(engine, livro_id: int) -> tuple[Livro, int]:
    """Define o livro da trilha. Cria o plano de sessões se ainda não existir.

    Devolve o livro e o número total de sessões.
    """
    with abrir_sessao(engine) as s:
        livro = s.get(Livro, livro_id)
        if livro is None:
            raise ValueError(f"Livro {livro_id} não existe.")

        existentes = s.exec(select(Sessao).where(Sessao.livro_id == livro_id)).all()
        if not existentes:
            caps = s.exec(select(Capitulo).where(Capitulo.livro_id == livro_id)).all()
            for ordem, plano in enumerate(planejar(list(caps)), start=1):
                s.add(Sessao(
                    livro_id=livro_id,
                    ordem=ordem,
                    capitulo_inicio_id=plano.capitulos[0].id,
                    capitulo_fim_id=plano.capitulos[-1].id,
                    pagina_inicio=plano.pagina_inicio,
                    pagina_fim=plano.pagina_fim,
                    caracteres=plano.caracteres,
                ))
            s.flush()

        # Só um livro fica ativo por vez; o progresso dos outros é guardado.
        for p in s.exec(select(Progresso).where(Progresso.ativo == True)).all():  # noqa: E712
            p.ativo = False
            s.add(p)
        progresso = s.exec(select(Progresso).where(Progresso.livro_id == livro_id)).first()
        if progresso is None:
            progresso = Progresso(livro_id=livro_id)
        progresso.ativo = True
        s.add(progresso)
        s.commit()

        total = len(s.exec(select(Sessao.id).where(Sessao.livro_id == livro_id)).all())
        s.refresh(livro)
        return livro, total


@dataclass
class Situacao:
    livro: Livro
    total: int
    concluidas: int  # entregues ou puladas
    proxima: Sessao | None
    titulo_cap_inicio: str = ""
    titulo_cap_fim: str = ""


def situacao_atual(engine) -> Situacao | None:
    """Livro ativo, quantas sessões já foram e qual é a próxima."""
    with abrir_sessao(engine) as s:
        progresso = s.exec(select(Progresso).where(Progresso.ativo == True)).first()  # noqa: E712
        if progresso is None:
            return None
        livro = s.get(Livro, progresso.livro_id)
        sessoes = s.exec(
            select(Sessao).where(Sessao.livro_id == livro.id).order_by(Sessao.ordem)
        ).all()
        proxima = next((x for x in sessoes if x.status == "pendente"), None)
        situacao = Situacao(
            livro=livro,
            total=len(sessoes),
            concluidas=sum(1 for x in sessoes if x.status != "pendente"),
            proxima=proxima,
        )
        if proxima:
            situacao.titulo_cap_inicio = s.get(Capitulo, proxima.capitulo_inicio_id).titulo
            situacao.titulo_cap_fim = s.get(Capitulo, proxima.capitulo_fim_id).titulo
        return situacao


def progresso_por_livro(engine) -> tuple[int | None, dict[int, tuple[int, int]]]:
    """Devolve (id do livro ativo, {livro_id: (sessões concluídas, total)}).

    Só aparecem no dicionário os livros que já tiveram trilha criada.
    """
    with abrir_sessao(engine) as s:
        ativo = s.exec(select(Progresso.livro_id).where(Progresso.ativo == True)).first()  # noqa: E712
        progresso = {}
        for sessao in s.exec(select(Sessao)).all():
            feitas, total = progresso.get(sessao.livro_id, (0, 0))
            progresso[sessao.livro_id] = (feitas + (sessao.status != "pendente"), total + 1)
    return ativo, progresso


def pular_proxima(engine) -> bool:
    """Marca a próxima sessão como pulada. Devolve False se não havia sessão."""
    with abrir_sessao(engine) as s:
        progresso = s.exec(select(Progresso).where(Progresso.ativo == True)).first()  # noqa: E712
        if progresso is None:
            return False
        proxima = s.exec(
            select(Sessao)
            .where(Sessao.livro_id == progresso.livro_id, Sessao.status == "pendente")
            .order_by(Sessao.ordem)
        ).first()
        if proxima is None:
            return False
        proxima.status = "pulada"
        s.add(proxima)
        s.commit()
        return True
