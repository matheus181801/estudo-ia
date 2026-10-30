"""Bot do MBA (@MbaMatheus_bot), no grupo com um tópico por matéria.

- Pergunta escrita num tópico → resposta baseada nas notas de todas as aulas
  daquela matéria (no tópico Geral, de todas as matérias).
- /revisao → gera na hora a revisão acumulada da matéria (simulado para prova).
- /aulas → lista as aulas e em que etapa cada uma está.

Só o Matheus é atendido: o bot confere quem escreveu, não só o grupo.
"""

import asyncio
import logging
from pathlib import Path

from sqlmodel import select
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from estudo_ia.bot.formatacao import dividir, markdown_para_html
from estudo_ia.config import Config
from estudo_ia.db import AulaMBA, Materia, abrir_sessao

log = logging.getLogger(__name__)

INSTRUCOES = """Você é o tutor do Matheus no MBA em AI Leadership. Ele não é da área de tecnologia.
Responda em português do Brasil, de forma clara e didática, usando as notas das aulas fornecidas.
Explique termos técnicos do zero (em inglês, com a explicação ao lado).
Diga de qual aula vem a informação (ex.: "na aula de 22/10"). Se as notas não cobrem a pergunta,
diga isso e, se ajudar, explique o conceito em linhas gerais deixando claro que não veio da aula."""


def notas_das_aulas(engine, materia_id: int | None) -> list[tuple[str, str]]:
    """[(rótulo, notas em texto)] das aulas com notas, de uma matéria ou de todas."""
    from estudo_ia.mba.filtro import NotasAula, notas_em_texto

    with abrir_sessao(engine) as s:
        consulta = select(AulaMBA, Materia).join(Materia).order_by(AulaMBA.data)
        if materia_id is not None:
            consulta = consulta.where(AulaMBA.materia_id == materia_id)
        linhas = s.exec(consulta).all()
    resultado = []
    for aula, materia in linhas:
        arquivo = Path(aula.pasta_local or "") / "notas.json"
        if arquivo.exists():
            notas = NotasAula.model_validate_json(arquivo.read_text(encoding="utf-8"))
            resultado.append((f"{materia.nome} · aula de {aula.data.strftime('%d/%m')}: {notas.titulo_aula}",
                              notas_em_texto(notas)))
    return resultado


def responder_pergunta(cliente, config: Config, notas: list[tuple[str, str]], pergunta: str) -> str:
    documentos = [{"type": "document", "title": rotulo,
                   "source": {"type": "text", "media_type": "text/plain", "data": texto}}
                  for rotulo, texto in notas]
    if documentos:
        documentos[-1]["cache_control"] = {"type": "ephemeral"}  # perguntas seguidas saem mais baratas
    resposta = cliente.messages.create(
        model=config.claude_modelo, max_tokens=4000, system=INSTRUCOES,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": documentos + [{"type": "text", "text": pergunta}]}],
    )
    return "".join(b.text for b in resposta.content if b.type == "text").strip()


def materia_do_topico(engine, topico_id: int | None) -> Materia | None:
    if topico_id is None:
        return None  # tópico Geral
    with abrir_sessao(engine) as s:
        return s.exec(select(Materia).where(Materia.topico_id == topico_id)).first()


def criar_app_mba(config: Config, engine) -> Application:
    from estudo_ia.leitura.claude_livro import criar_cliente

    cliente = criar_cliente(config)
    # Só mensagens do Matheus (o chat privado dele tem o mesmo id do usuário).
    so_matheus = filters.User(user_id=int(config.telegram_chat_id))

    async def responder(update: Update, texto: str):
        for parte in dividir(texto):
            try:
                await update.message.reply_text(markdown_para_html(parte), parse_mode=ParseMode.HTML)
            except Exception:
                await update.message.reply_text(parte)

    def topico(update: Update) -> int | None:
        return update.message.message_thread_id if update.message.is_topic_message else None

    async def pergunta(update: Update, context: ContextTypes.DEFAULT_TYPE):
        materia = materia_do_topico(engine, topico(update))
        notas = notas_das_aulas(engine, materia.id if materia else None)
        if not notas:
            await update.message.reply_text("Ainda não tenho aulas processadas aqui.")
            return
        aviso = await update.message.reply_text("🔎 Consultando as aulas...")
        try:
            texto = await asyncio.to_thread(responder_pergunta, cliente, config, notas, update.message.text)
        except Exception as erro:
            log.exception("Erro ao responder no MBA")
            await aviso.edit_text(f"😕 Não consegui responder agora ({type(erro).__name__}).")
            return
        await aviso.delete()
        await responder(update, texto)

    async def cmd_revisao(update: Update, context: ContextTypes.DEFAULT_TYPE):
        from estudo_ia.mba.processador import atualizar_revisao_materia

        materia = materia_do_topico(engine, topico(update))
        if materia is None:
            await update.message.reply_text("Use /revisao dentro do tópico da matéria.")
            return
        await update.message.reply_text(f"🔁 Gerando a revisão de {materia.nome}... leva uns 2 minutos.")
        try:
            pdf = await asyncio.to_thread(atualizar_revisao_materia, engine, config,
                                          cliente.with_options(timeout=600.0), materia)
        except Exception as erro:
            log.exception("Erro na revisão")
            await update.message.reply_text(f"😕 Não consegui gerar a revisão ({type(erro).__name__}).")
            return
        if pdf:
            with open(pdf, "rb") as f:
                await update.message.reply_document(f, filename=f"Revisao - {materia.nome}.pdf",
                                                    caption=f"🔁 Revisão de {materia.nome}",
                                                    write_timeout=300, read_timeout=120)

    async def cmd_aulas(update: Update, context: ContextTypes.DEFAULT_TYPE):
        from estudo_ia.mba.processador import DESCRICAO

        with abrir_sessao(engine) as s:
            linhas = s.exec(select(AulaMBA, Materia).join(Materia).order_by(AulaMBA.data)).all()
        texto = "\n".join(f"{a.data.strftime('%d/%m')} · {m.nome} — {DESCRICAO.get(a.etapa, a.etapa)}"
                          for a, m in linhas) or "Nenhuma aula encontrada ainda."
        await update.message.reply_text("🎓 Aulas do MBA\n\n" + texto)

    app = Application.builder().token(config.telegram_bot_token_mba).build()
    app.add_handler(CommandHandler("revisao", cmd_revisao, filters=so_matheus))
    app.add_handler(CommandHandler("aulas", cmd_aulas, filters=so_matheus))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & so_matheus, pergunta))
    return app
