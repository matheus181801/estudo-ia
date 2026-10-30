"""Processamento das aulas do MBA, do Drive até o tópico da matéria.

Cada aula passa por etapas, e a etapa atual fica gravada no banco. Se algo
falhar no meio, a próxima rodada continua de onde parou (sem pagar de novo):

    nova → notas → pacote → midia → revisao → pronta → entregue

O Drive ("Aprofundamento das Aulas") é a memória oficial: cada aula pronta
ganha lá os arquivos, as notas (notas.json) e um estado.json com o tópico do
Telegram. Assim, se a aula foi processada no notebook, a VPS só importa.

O andamento também vai para data/mba/progresso.json, que o mod do app mostra.
"""

import json
import logging
import re
import unicodedata
from datetime import date, datetime, time, timedelta
from pathlib import Path

from sqlmodel import select

from estudo_ia.config import Config
from estudo_ia.db import AulaMBA, Materia, abrir_sessao
from estudo_ia.mba.aulas import (MATERIA_GERAL, anonimizar_transcricao, escolher_arquivos,
                                 identificar_aula, texto_docx, texto_pdf)
from estudo_ia.mba.drive import PonteDrive

log = logging.getLogger(__name__)

ETAPAS = ["nova", "notas", "pacote", "midia", "revisao", "pronta", "entregue"]
DESCRICAO = {
    "nova": "na fila", "notas": "notas da aula prontas", "pacote": "pacote de texto pronto",
    "midia": "podcast e vídeo prontos", "revisao": "revisão da matéria pronta",
    "pronta": "pronta para entregar", "entregue": "entregue", "erro": "erro",
}


def slug(texto: str) -> str:
    """Nome seguro para pasta: sem acentos e sem caracteres especiais."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9.]+", "-", sem_acento).strip("-")[:80]


def criar_ponte(config: Config) -> PonteDrive:
    return PonteDrive(config.drive_ponte_url, config.drive_ponte_chave)


# ---------------------------------------------------------------- progresso

class Progresso:
    """Grava o andamento em data/mba/progresso.json (lido pelo mod do app)."""

    def __init__(self, config: Config):
        self.arquivo = config.data_dir / "mba" / "progresso.json"
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)

    def atualizar(self, engine, atual: str = "", detalhe: str = "") -> None:
        with abrir_sessao(engine) as s:
            linhas = s.exec(select(AulaMBA, Materia).join(Materia).order_by(AulaMBA.data)).all()
        aulas = [{
            "titulo": a.titulo, "materia": m.nome, "data": a.data.isoformat(), "etapa": a.etapa,
            "descricao": DESCRICAO.get(a.etapa, a.etapa), "erro": a.erro,
            "passo": ETAPAS.index(a.etapa) if a.etapa in ETAPAS else -1, "total_passos": len(ETAPAS) - 1,
        } for a, m in linhas]
        dados = {"atualizado": datetime.now().isoformat(timespec="seconds"),
                 "trabalhando_em": atual, "detalhe": detalhe, "aulas": aulas}
        temporario = self.arquivo.with_suffix(".tmp")
        temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        temporario.replace(self.arquivo)  # troca de uma vez: o mod nunca lê um arquivo pela metade


# ---------------------------------------------------------------- banco

def obter_materia(engine, nome: str) -> Materia:
    with abrir_sessao(engine) as s:
        materia = s.exec(select(Materia).where(Materia.nome == nome)).first()
        if materia is None:
            materia = Materia(nome=nome)
            s.add(materia)
            s.commit()
            s.refresh(materia)
        return materia


def _salvar(engine, aula: AulaMBA, **campos) -> AulaMBA:
    with abrir_sessao(engine) as s:
        atual = s.get(AulaMBA, aula.id)
        for nome, valor in campos.items():
            setattr(atual, nome, valor)
        atual.atualizado_em = datetime.now()
        s.add(atual)
        s.commit()
        s.refresh(atual)
        return atual


def pasta_da_aula(config: Config, materia: str, titulo: str) -> Path:
    return config.data_dir / "mba" / slug(materia) / slug(titulo)


def aulas_da_materia(engine, materia_id: int) -> list[AulaMBA]:
    with abrir_sessao(engine) as s:
        return list(s.exec(select(AulaMBA).where(AulaMBA.materia_id == materia_id).order_by(AulaMBA.data)).all())


# ---------------------------------------------------------------- sincronizar

def sincronizar(engine, config: Config, ponte: PonteDrive, avisar=print) -> list[str]:
    """Registra as aulas novas do Drive. As que já foram processadas são só importadas."""
    processadas = ponte.listar_processadas()
    novas = []
    with abrir_sessao(engine) as s:
        conhecidas = set(s.exec(select(AulaMBA.pasta_id)).all())

    for pasta in ponte.listar_aulas():
        identificada = identificar_aula(pasta.nome)
        if identificada is None or pasta.id in conhecidas:
            continue
        materia = obter_materia(engine, identificada.materia)
        local = pasta_da_aula(config, materia.nome, pasta.nome)
        aula = AulaMBA(pasta_id=pasta.id, titulo=pasta.nome, data=identificada.data,
                       materia_id=materia.id, pasta_local=str(local))

        # Já processada (no notebook ou antes de um reinício)? Importa notas e estado do Drive.
        feita = next((a for a in processadas.get(materia.nome, []) if a.nome == pasta.nome), None)
        arquivos = {f.nome: f for f in feita.arquivos} if feita else {}
        if "notas.json" in arquivos and "estado.json" in arquivos:
            local.mkdir(parents=True, exist_ok=True)
            for nome in ("notas.json", "pacote.json", "estado.json"):
                if nome in arquivos:
                    (local / nome).write_bytes(ponte.baixar(arquivos[nome].id))
            estado = json.loads((local / "estado.json").read_text(encoding="utf-8"))
            aula.etapa = "entregue" if estado.get("entregue") else "pronta"
            aula.professor = estado.get("professor", "")
            if estado.get("topico_id") and not materia.topico_id:
                with abrir_sessao(engine) as s:
                    m = s.get(Materia, materia.id)
                    m.topico_id = estado["topico_id"]
                    s.add(m)
                    s.commit()
            avisar(f"Importada do Drive (já processada): {pasta.nome}")
        else:
            novas.append(pasta.nome)
            avisar(f"Aula nova: {pasta.nome}")
        with abrir_sessao(engine) as s:
            s.add(aula)
            s.commit()
    return novas


# ---------------------------------------------------------------- processar

def _revisao_espacada(engine, aula: AulaMBA) -> list:
    """Uma questão de cada uma das até 3 aulas anteriores da mesma matéria."""
    from estudo_ia.pacote.modelos import QuestaoMultipla

    questoes = []
    anteriores = [a for a in aulas_da_materia(engine, aula.materia_id) if a.data < aula.data]
    for anterior in reversed(anteriores[-3:]):
        arquivo = Path(anterior.pasta_local or "") / "pacote.json"
        if arquivo.exists():
            lista = json.loads(arquivo.read_text(encoding="utf-8"))["conteudo"]["multipla_escolha"]
            if lista:
                questoes.append(QuestaoMultipla.model_validate(lista[date.today().toordinal() % len(lista)]))
    return questoes


def processar_aula(engine, config: Config, ponte: PonteDrive, aula_id: int,
                   progresso: Progresso | None = None, avisar=print) -> AulaMBA:
    """Leva uma aula até "pronta", continuando da etapa em que parou."""
    from estudo_ia.leitura.claude_livro import criar_cliente
    from estudo_ia.mba.filtro import NotasAula, extrair_notas
    from estudo_ia.mba.pacote import gerar_pacote_aula, sumario_biblioteca
    from estudo_ia.pacote.modelos import Pacote
    from estudo_ia.pacote.renderizar import gerar_arquivos

    with abrir_sessao(engine) as s:
        aula = s.get(AulaMBA, aula_id)
        materia = s.get(Materia, aula.materia_id)
    pasta = Path(aula.pasta_local)
    pasta.mkdir(parents=True, exist_ok=True)
    cliente = criar_cliente(config).with_options(timeout=600.0)

    def passo(texto: str):
        avisar(f"[{aula.titulo}] {texto}")
        if progresso:
            progresso.atualizar(engine, atual=aula.titulo, detalhe=texto)

    if aula.etapa == "erro":
        # Retoma da última etapa que deixou arquivo pronto (não refaz nem paga de novo).
        aula = _salvar(engine, aula, etapa=etapa_pelos_arquivos(pasta), erro=None)

    if aula.etapa == "nova" and not (pasta / "notas.json").exists():
        passo("Baixando material e transcrição do Drive...")
        pasta_drive = next(p for p in ponte.listar_aulas() if p.id == aula.pasta_id)
        materiais, transcricoes = escolher_arquivos(pasta_drive.arquivos)
        material = "\n\n".join(texto_pdf(ponte.baixar(m.id)) for m in materiais)
        bruto = "\n".join(texto_docx(ponte.baixar(t.id)) for t in transcricoes)
        professor, transcricao = anonimizar_transcricao(bruto)
        passo("Filtrando a transcrição (só o conteúdo)...")
        notas = extrair_notas(cliente, config, materia.nome, professor, material, transcricao)
        (pasta / "notas.json").write_text(notas.model_dump_json(indent=2), encoding="utf-8")
        aula = _salvar(engine, aula, etapa="notas", professor=professor, erro=None)
    elif aula.etapa == "nova":
        aula = _salvar(engine, aula, etapa="notas", erro=None)

    if aula.etapa == "notas":
        notas = NotasAula.model_validate_json((pasta / "notas.json").read_text(encoding="utf-8"))
        numero = [a.id for a in aulas_da_materia(engine, aula.materia_id)].index(aula.id) + 1
        passo("Gerando o pacote (pesquisa web, newsletter, glossário, questões)...")
        pacote = gerar_pacote_aula(cliente, config, notas, materia.nome, _nome_curto(aula.professor),
                                   numero, aula.data, sumario_biblioteca(engine),
                                   _revisao_espacada(engine, aula), avisar=passo)
        (pasta / "pacote.json").write_text(pacote.model_dump_json(indent=2), encoding="utf-8")
        passo("Montando HTML e PDF...")
        gerar_arquivos(pacote, pasta)
        aula = _salvar(engine, aula, etapa="pacote")

    if aula.etapa == "pacote":
        pacote = Pacote.model_validate_json((pasta / "pacote.json").read_text(encoding="utf-8"))
        # Podcast e vídeo enriquecem, mas não travam a aula: se falharem, ela segue sem eles.
        try:
            from estudo_ia.podcast.servico import gerar_podcast
            passo("Gerando o podcast curto...")
            gerar_podcast(pacote, pasta, config, avisar=passo)
        except Exception as erro:
            log.exception("Podcast da aula falhou")
            passo(f"! Podcast falhou ({type(erro).__name__}); seguindo sem ele.")
        try:
            from estudo_ia.video.servico import gerar_video
            passo("Gerando a vídeo-aula...")
            gerar_video(pacote, pasta, config, avisar=passo)
        except Exception as erro:
            log.exception("Vídeo da aula falhou")
            passo(f"! Vídeo falhou ({type(erro).__name__}); seguindo sem ele.")
        aula = _salvar(engine, aula, etapa="midia")

    if aula.etapa == "midia":
        passo("Atualizando a revisão acumulada da matéria...")
        try:
            atualizar_revisao_materia(engine, config, cliente, materia)
        except Exception as erro:
            log.exception("Revisão da matéria falhou")
            passo(f"! Revisão da matéria falhou ({type(erro).__name__}); seguindo sem ela.")
        aula = _salvar(engine, aula, etapa="revisao")

    if aula.etapa == "revisao":
        passo("Salvando no Google Drive...")
        salvar_no_drive(ponte, materia, aula, pasta, entregue=False)
        aula = _salvar(engine, aula, etapa="pronta")
        passo("Pronta para entregar.")
    return aula


def etapa_pelos_arquivos(pasta: Path) -> str:
    """Descobre até onde a aula chegou olhando os arquivos já gerados."""
    if (pasta / "pacote.pdf").exists():
        return "pacote"
    if (pasta / "notas.json").exists():
        return "notas"
    return "nova"


def _nome_curto(professor: str) -> str:
    """'Igor Pinheiro Lagreca de Sales Cabral' → 'Igor' (como nos materiais: "Prof. Igor")."""
    return professor.split()[0] if professor.strip() else "professor(a)"


def revisao_materia_arquivo(config: Config, materia: Materia) -> Path:
    return config.data_dir / "mba" / slug(materia.nome) / "Revisao-da-materia.pdf"


def atualizar_revisao_materia(engine, config: Config, cliente, materia: Materia) -> Path | None:
    from estudo_ia.mba.filtro import NotasAula, notas_em_texto
    from estudo_ia.mba.revisao import gerar_pdf_revisao, gerar_revisao

    notas = []
    for aula in aulas_da_materia(engine, materia.id):
        arquivo = Path(aula.pasta_local or "") / "notas.json"
        if arquivo.exists():
            n = NotasAula.model_validate_json(arquivo.read_text(encoding="utf-8"))
            notas.append((f"Aula de {aula.data.strftime('%d/%m')}: {n.titulo_aula}", notas_em_texto(n)))
    if not notas:
        return None
    revisao = gerar_revisao(cliente, config, materia.nome, notas)
    return gerar_pdf_revisao(revisao, materia.nome, len(notas), revisao_materia_arquivo(config, materia))


ARQUIVOS_DRIVE = [
    ("pacote.pdf", "application/pdf"), ("newsletter.html", "text/html"),
    ("podcast.mp3", "audio/mpeg"), ("video.mp4", "video/mp4"),
    ("notas.json", "application/json"), ("pacote.json", "application/json"),
]


def salvar_no_drive(ponte: PonteDrive, materia: Materia, aula: AulaMBA, pasta: Path, entregue: bool) -> None:
    caminho = [materia.nome, aula.titulo]
    for nome, tipo in ARQUIVOS_DRIVE:
        if (pasta / nome).exists():
            ponte.salvar(caminho, nome, (pasta / nome).read_bytes(), tipo)
    revisao = pasta.parent / "Revisao-da-materia.pdf"
    if revisao.exists():
        ponte.salvar([materia.nome], "Revisão da matéria.pdf", revisao.read_bytes(), "application/pdf")
    estado = {"entregue": entregue, "topico_id": materia.topico_id, "professor": aula.professor}
    ponte.salvar(caminho, "estado.json", json.dumps(estado).encode(), "application/json")


# ---------------------------------------------------------------- entregar

def hora_de_entregar(aula: AulaMBA, config: Config, agora: datetime | None = None) -> bool:
    """Regra: às HORA_ENTREGA_MBA (06:30) do dia seguinte à aula."""
    agora = agora or datetime.now()
    h, m = (int(x) for x in config.hora_entrega_mba.split(":"))
    return agora >= datetime.combine(aula.data + timedelta(days=1), time(h, m))


def entregar_aula(engine, config: Config, ponte: PonteDrive, aula_id: int, avisar=print) -> list[str]:
    from estudo_ia.mba import telegram_mba
    from estudo_ia.pacote.modelos import Pacote

    with abrir_sessao(engine) as s:
        aula = s.get(AulaMBA, aula_id)
        materia = s.get(Materia, aula.materia_id)
    pasta = Path(aula.pasta_local)
    pacote = Pacote.model_validate_json((pasta / "pacote.json").read_text(encoding="utf-8"))

    if materia.topico_id is None and materia.nome != MATERIA_GERAL:
        topico = telegram_mba.criar_topico(config, materia.nome)
        with abrir_sessao(engine) as s:
            m = s.get(Materia, materia.id)
            m.topico_id = topico
            s.add(m)
            s.commit()
            s.refresh(m)
            materia = m

    texto = (f"🎓 Aula {pacote.sessao_ordem} · {aula.data.strftime('%d/%m')} · Prof. {pacote.autor}\n"
             f"{pacote.conteudo.titulo}\n\n{pacote.conteudo.abertura}")
    arquivos = [(pasta / "pacote.pdf", "📄 Newsletter, glossário, questões e gabarito"),
                (pasta / "podcast.mp3", "🎧 Podcast da aula"),
                (pasta / "video.mp4", "🎬 Vídeo-aula de revisão"),
                (revisao_materia_arquivo(config, materia), f"🔁 Revisão acumulada de {materia.nome}")]
    avisos = telegram_mba.enviar_no_topico(config, materia.topico_id, texto, arquivos)

    try:
        from estudo_ia.entrega.email import enviar_email
        html = (pasta / "newsletter.html").read_text(encoding="utf-8")
        enviar_email(config, f"🎓 {materia.nome} · Aula {pacote.sessao_ordem}: {pacote.conteudo.titulo}",
                     html, pasta / "pacote.pdf")
    except Exception as erro:
        log.exception("E-mail da aula falhou")
        avisos.append(f"e-mail falhou ({type(erro).__name__})")

    _salvar(engine, aula, etapa="entregue")
    estado = {"entregue": True, "topico_id": materia.topico_id, "professor": aula.professor}
    ponte.salvar([materia.nome, aula.titulo], "estado.json", json.dumps(estado).encode(), "application/json")
    avisar(f"Entregue: {aula.titulo}" + (f" (avisos: {'; '.join(avisos)})" if avisos else ""))
    return avisos


# ---------------------------------------------------------------- ciclo

def ciclo(engine, config: Config, entregar_ja: bool = False, avisar=print) -> None:
    """Uma rodada completa: aulas novas → processar o que falta → entregar o que está na hora."""
    ponte = criar_ponte(config)
    progresso = Progresso(config)
    sincronizar(engine, config, ponte, avisar=avisar)
    progresso.atualizar(engine)

    with abrir_sessao(engine) as s:
        pendentes = s.exec(select(AulaMBA).where(AulaMBA.etapa.not_in(["pronta", "entregue"]))
                           .order_by(AulaMBA.data)).all()
    for aula in pendentes:
        try:
            processar_aula(engine, config, ponte, aula.id, progresso, avisar=avisar)
        except Exception as erro:
            log.exception("Falha ao processar %s", aula.titulo)
            _salvar(engine, aula, etapa="erro", erro=f"{type(erro).__name__}: {str(erro)[:200]}")
            avisar(f"! Erro em {aula.titulo}: {erro}")
        progresso.atualizar(engine)

    with abrir_sessao(engine) as s:
        prontas = s.exec(select(AulaMBA).where(AulaMBA.etapa == "pronta").order_by(AulaMBA.data)).all()
    for aula in prontas:
        if entregar_ja or hora_de_entregar(aula, config):
            try:
                entregar_aula(engine, config, ponte, aula.id, avisar=avisar)
            except Exception as erro:
                log.exception("Falha ao entregar %s", aula.titulo)
                avisar(f"! Não consegui entregar {aula.titulo}: {erro}")
    progresso.atualizar(engine, atual="", detalhe="Rodada concluída.")
