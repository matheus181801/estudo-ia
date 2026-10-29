"""Bot do Telegram (long polling).

Long polling: o próprio bot fica perguntando ao Telegram "chegou mensagem
nova?" a cada poucos segundos. Por isso ele roda no notebook ou na VPS sem
precisar de domínio nem HTTPS (o que um webhook exigiria).

Segurança: o bot só responde ao chat_id do Matheus. Mensagens de qualquer
outra pessoa são ignoradas em silêncio.
"""

import asyncio
import logging

from sqlmodel import select
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from estudo_ia.bot.formatacao import dividir, markdown_para_html, normalizar
from estudo_ia.config import Config
from estudo_ia.db import Livro, abrir_sessao
from estudo_ia.ingestao import file_search
from estudo_ia.ingestao.biblioteca import listar_livros
from estudo_ia.trilha import planejador

log = logging.getLogger(__name__)

AJUDA = """<b>Estudo IA</b> 📚

Mande qualquer pergunta sobre os seus livros e eu respondo citando livro e capítulo.

/livros — lista os livros da biblioteca
/livro &lt;número ou nome&gt; — escolhe o livro da trilha
/status — em que ponto da trilha você está
/proximo — o que vem na próxima sessão
/pular — pula a próxima sessão
/pacote — gera o pacote do dia agora"""


async def responder(update: Update, texto_markdown: str) -> None:
    """Envia um texto longo em várias mensagens, com formatação."""
    for parte in dividir(texto_markdown):
        try:
            await update.message.reply_text(markdown_para_html(parte), parse_mode=ParseMode.HTML)
        except Exception:
            # Se a formatação der problema, manda como texto puro.
            await update.message.reply_text(parte)


def encontrar_livro(engine, busca: str) -> list[Livro]:
    """Acha livros pelo número (id) ou por um pedaço do título/autor."""
    with abrir_sessao(engine) as s:
        if busca.strip().isdigit():
            livro = s.get(Livro, int(busca))
            return [livro] if livro else []
        termo = normalizar(busca)
        livros = s.exec(select(Livro)).all()
        return [l for l in livros if termo in normalizar(f"{l.titulo} {l.autor}")]


def criar_app(config: Config, engine) -> Application:
    if not config.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN está vazio no .env.")
    if not config.telegram_chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID está vazio no .env.")

    cliente = file_search.criar_cliente(config)
    store = file_search.obter_store(cliente, config)
    so_matheus = filters.Chat(chat_id=int(config.telegram_chat_id))

    async def cmd_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(AJUDA, parse_mode=ParseMode.HTML)

    async def cmd_livros(update: Update, context: ContextTypes.DEFAULT_TYPE):
        linhas = ["**Biblioteca**", ""]
        for livro, capitulos, _ in listar_livros(engine):
            linhas.append(f"{livro.id}. {livro.titulo} ({capitulos} cap.)")
        linhas += ["", "Para escolher: /livro 16 ou /livro inspired"]
        await responder(update, "\n".join(linhas))

    async def cmd_livro(update: Update, context: ContextTypes.DEFAULT_TYPE):
        busca = " ".join(context.args)
        if not busca:
            await update.message.reply_text("Diga qual livro: /livro 16 ou /livro inspired")
            return
        achados = encontrar_livro(engine, busca)
        if not achados:
            await update.message.reply_text("Não achei esse livro. Veja a lista em /livros")
            return
        if len(achados) > 1:
            opcoes = "\n".join(f"{l.id}. {l.titulo}" for l in achados[:10])
            await update.message.reply_text(f"Achei mais de um. Use o número:\n{opcoes}")
            return
        livro, total = planejador.escolher_livro(engine, achados[0].id)
        await responder(update, f"✅ Trilha definida: **{livro.titulo}**\n{total} sessões de ~90 minutos.\n\nVeja a primeira com /proximo")

    async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
        sit = planejador.situacao_atual(engine)
        if sit is None:
            await update.message.reply_text("Nenhum livro na trilha ainda. Escolha com /livro")
            return
        porcentagem = round(100 * sit.concluidas / max(1, sit.total))
        barra = "▓" * (porcentagem // 10) + "░" * (10 - porcentagem // 10)
        await responder(update, f"📖 **{sit.livro.titulo}**\n{barra} {porcentagem}%\nSessões: {sit.concluidas} de {sit.total}")

    async def cmd_proximo(update: Update, context: ContextTypes.DEFAULT_TYPE):
        sit = planejador.situacao_atual(engine)
        if sit is None:
            await update.message.reply_text("Nenhum livro na trilha ainda. Escolha com /livro")
            return
        if sit.proxima is None:
            await update.message.reply_text("🎉 Você terminou este livro! Escolha outro com /livro")
            return
        s = sit.proxima
        caps = sit.titulo_cap_inicio if sit.titulo_cap_inicio == sit.titulo_cap_fim \
            else f"{sit.titulo_cap_inicio}\naté {sit.titulo_cap_fim}"
        paginas_aprox = round(s.caracteres / 2000)
        await responder(update, (
            f"**Próxima sessão ({s.ordem} de {sit.total})**\n{caps}\n\n"
            f"Páginas {s.pagina_inicio}–{s.pagina_fim} do arquivo · ~{paginas_aprox} páginas de leitura"
        ))

    async def cmd_pular(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if planejador.pular_proxima(engine):
            await update.message.reply_text("⏭️ Sessão pulada. Veja a nova próxima com /proximo")
        else:
            await update.message.reply_text("Não há sessão para pular. Escolha um livro com /livro")

    async def cmd_pacote(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🛠️ O pacote diário chega na Fase 3. Por enquanto, pergunte o que quiser sobre os livros!")

    async def pergunta(update: Update, context: ContextTypes.DEFAULT_TYPE):
        aviso = await update.message.reply_text("🔎 Buscando nos livros...")
        await update.message.chat.send_action(ChatAction.TYPING)
        try:
            # A chamada ao Gemini é "bloqueante"; rodamos numa thread para o bot
            # continuar respondendo enquanto espera.
            resposta = await asyncio.to_thread(
                file_search.perguntar, cliente, store, config, update.message.text
            )
        except Exception as erro:
            log.exception("Erro ao responder pergunta")
            await aviso.edit_text(f"😕 Não consegui responder agora ({type(erro).__name__}). Tente de novo em instantes.")
            return
        await aviso.delete()
        await responder(update, resposta.texto or "Não encontrei resposta nos livros.")

    app = Application.builder().token(config.telegram_bot_token).build()
    app.add_handler(CommandHandler(["start", "ajuda", "help"], cmd_ajuda, filters=so_matheus))
    app.add_handler(CommandHandler("livros", cmd_livros, filters=so_matheus))
    app.add_handler(CommandHandler("livro", cmd_livro, filters=so_matheus))
    app.add_handler(CommandHandler("status", cmd_status, filters=so_matheus))
    app.add_handler(CommandHandler("proximo", cmd_proximo, filters=so_matheus))
    app.add_handler(CommandHandler("pular", cmd_pular, filters=so_matheus))
    app.add_handler(CommandHandler("pacote", cmd_pacote, filters=so_matheus))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & so_matheus, pergunta))
    return app


def rodar(config: Config, engine) -> None:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    # A biblioteca httpx registra cada URL chamada, e a URL do Telegram contém
    # o token do bot. Subimos o nível do log dela para o token não ir parar no log.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    app = criar_app(config, engine)
    log.info("Bot rodando. Aperte Ctrl+C para parar.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
