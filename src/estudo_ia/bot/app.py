"""Bot do Telegram (long polling).

Long polling: o próprio bot fica perguntando ao Telegram "chegou mensagem
nova?" a cada poucos segundos. Por isso ele roda no notebook ou na VPS sem
precisar de domínio nem HTTPS (o que um webhook exigiria).

Segurança: o bot só responde ao chat_id do Matheus. Mensagens de qualquer
outra pessoa são ignoradas em silêncio.
"""

import asyncio
import logging
import tempfile
from pathlib import Path

from sqlmodel import select
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

from estudo_ia.bot import roteador
from estudo_ia.bot.banco import instalar_banco
from estudo_ia.bot.formatacao import dividir, markdown_para_html, normalizar
from estudo_ia.bot.teclados import teclado_comecar, teclado_livros
from estudo_ia.config import Config
from estudo_ia.db import Livro, abrir_sessao
from estudo_ia.entrega import pipeline
from estudo_ia.ingestao import file_search
from estudo_ia.ingestao.biblioteca import listar_livros
from estudo_ia.leitura import claude_livro
from estudo_ia.pacote.servico import criar_pacote
from estudo_ia.trilha import planejador

log = logging.getLogger(__name__)

AJUDA = """<b>Estudo IA</b> 📚

Mande qualquer pergunta e eu respondo citando livro e capítulo.
Perguntas sobre o livro da trilha são respondidas pelo Claude, que lê o livro inteiro.
Para buscar em toda a biblioteca, use /geral ou fale em "outros livros".

/geral &lt;pergunta&gt; — pergunta sobre toda a biblioteca
/livros — mostra os livros como botões para você escolher o que estudar
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


def texto_proxima_sessao(sit) -> str:
    """Descrição da próxima sessão (capítulos e páginas), em Markdown."""
    if sit is None:
        return "Nenhum livro na trilha ainda. Escolha com /livros"
    if sit.proxima is None:
        return "🎉 Você terminou este livro! Escolha outro com /livros"
    s = sit.proxima
    caps = sit.titulo_cap_inicio if sit.titulo_cap_inicio == sit.titulo_cap_fim \
        else f"{sit.titulo_cap_inicio}\naté {sit.titulo_cap_fim}"
    paginas_aprox = round(s.caracteres / 2000)
    return (f"**Próxima sessão ({s.ordem} de {sit.total})**\n{caps}\n\n"
            f"Páginas {s.pagina_inicio}–{s.pagina_fim} do arquivo · ~{paginas_aprox} páginas de leitura")


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
    cliente_claude = claude_livro.criar_cliente(config)
    so_matheus = filters.Chat(chat_id=int(config.telegram_chat_id))

    async def cmd_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(AJUDA, parse_mode=ParseMode.HTML)
        await enviar_lista_livros(update.message)

    async def cmd_livros(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await enviar_lista_livros(update.message)

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
        await responder(update, texto_proxima_sessao(planejador.situacao_atual(engine)))

    # ---------- Escolha do livro por botões ----------

    async def enviar_lista_livros(mensagem):
        await mensagem.reply_text("📚 Escolha o livro que você quer estudar:",
                                  reply_markup=teclado_livros(engine))

    gerando = asyncio.Lock()  # evita gerar dois pacotes ao mesmo tempo (toque duplo no botão)

    def gerar_e_entregar() -> bool:
        pacote_id = pipeline.gerar(engine, config, avisar=log.info)
        return pacote_id is not None and pipeline.entregar(engine, config, pacote_id, avisar=log.info)

    async def ao_tocar_botao(update: Update, context: ContextTypes.DEFAULT_TYPE):
        consulta = update.callback_query
        if consulta.message.chat.id != int(config.telegram_chat_id):
            await consulta.answer()  # botão tocado fora do chat do Matheus: ignora
            return
        await consulta.answer()  # tira o "carregando" do botão no celular

        if consulta.data.startswith("livro:"):
            livro, total = planejador.escolher_livro(engine, int(consulta.data.split(":")[1]))
            texto = (f"✅ Trilha definida: **{livro.titulo}**\n{total} sessões de ~90 minutos.\n\n"
                     + texto_proxima_sessao(planejador.situacao_atual(engine))
                     + "\n\nQuer receber o pacote desta sessão agora?")
            await consulta.edit_message_text(markdown_para_html(texto), parse_mode=ParseMode.HTML,
                                             reply_markup=teclado_comecar())

        elif consulta.data == "amanha":
            await consulta.edit_message_reply_markup(reply_markup=None)
            await consulta.message.reply_text(f"⏰ Combinado! O pacote chega amanhã às {config.hora_entrega}.")

        elif consulta.data == "comecar":
            await consulta.edit_message_reply_markup(reply_markup=None)
            if gerando.locked():
                await consulta.message.reply_text("⏳ Já estou gerando um pacote, só um instante.")
                return
            # Roda em segundo plano: o bot continua respondendo perguntas enquanto isso.
            context.application.create_task(gerar_em_segundo_plano(consulta.message))

    async def gerar_em_segundo_plano(mensagem):
        async with gerando:
            await mensagem.reply_text(
                "🚀 Gerando o pacote completo: newsletter, questões, podcast e vídeo.\n"
                "Leva uns 20 a 30 minutos; os arquivos chegam aqui e no e-mail. "
                "Enquanto isso, pode continuar perguntando.")
            try:
                ok = await asyncio.to_thread(gerar_e_entregar)
            except Exception:
                log.exception("Erro ao gerar o pacote pelo botão")
                ok = False
            if not ok:
                await mensagem.reply_text("😕 Não consegui entregar o pacote agora. "
                                          "Veja os alertas acima; tento de novo às 04:00.")

    async def cmd_pular(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if planejador.pular_proxima(engine):
            await update.message.reply_text("⏭️ Sessão pulada. Veja a nova próxima com /proximo")
        else:
            await update.message.reply_text("Não há sessão para pular. Escolha um livro com /livro")

    async def cmd_pacote(update: Update, context: ContextTypes.DEFAULT_TYPE):
        aviso = await update.message.reply_text("🛠️ Gerando o pacote da próxima sessão... leva uns 2 minutos.")
        try:
            arquivos = await asyncio.to_thread(criar_pacote, engine, config, False, log.info)
        except Exception as erro:
            log.exception("Erro ao gerar pacote")
            await aviso.edit_text(f"😕 Não consegui gerar o pacote: {erro}")
            return
        await aviso.delete()
        with open(arquivos.pdf, "rb") as pdf:
            await update.message.reply_document(pdf, filename=f"{arquivos.pasta.name}.pdf",
                                                caption=f"📚 {arquivos.titulo}")

    def responder_com_gemini(texto: str) -> str:
        resposta = file_search.perguntar(cliente, store, config, texto)
        return resposta.texto or "Não encontrei resposta nos livros."

    def responder_pergunta(texto: str, forcar_geral: bool = False) -> str:
        """Escolhe Claude (livro da trilha) ou Gemini (biblioteca toda)."""
        situacao = planejador.situacao_atual(engine)
        caminho = roteador.GEMINI if forcar_geral else \
            roteador.escolher_caminho(texto, tem_livro_ativo=situacao is not None)
        if caminho == roteador.CLAUDE:
            try:
                resposta = claude_livro.perguntar_livro(cliente_claude, config, engine, situacao.livro.id, texto)
                if not resposta.recusou:
                    return resposta.texto
                log.warning("Claude recusou a pergunta; usando o Gemini")
            except Exception:
                log.exception("Falha no Claude; usando o Gemini")
        return responder_com_gemini(texto)

    async def processar(update: Update, texto: str, forcar_geral: bool = False):
        origem = "toda a biblioteca" if forcar_geral else "nos livros"
        aviso = await update.message.reply_text(f"🔎 Buscando {origem}...")
        await update.message.chat.send_action(ChatAction.TYPING)
        try:
            # As chamadas às IAs são "bloqueantes"; rodamos numa thread para o bot
            # continuar respondendo enquanto espera.
            texto_resposta = await asyncio.to_thread(responder_pergunta, texto, forcar_geral)
        except Exception as erro:
            log.exception("Erro ao responder pergunta")
            await aviso.edit_text(f"😕 Não consegui responder agora ({type(erro).__name__}). Tente de novo em instantes.")
            return
        await aviso.delete()
        await responder(update, texto_resposta)

    async def cmd_importar(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Responda à mensagem com o banco (.db.gz) usando /importar."""
        original = update.message.reply_to_message
        if not original or not original.document or not original.document.file_name.endswith(".db.gz"):
            await update.message.reply_text("Responda à mensagem que tem o arquivo do banco (.db.gz) com /importar.")
            return
        aviso = await update.message.reply_text("📥 Baixando e conferindo o banco...")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                arquivo = Path(tmp) / original.document.file_name
                # Tempos maiores: por padrão a biblioteca espera só 5 s, pouco para 4–5 MB.
                tempos = {"read_timeout": 120, "connect_timeout": 30}
                arquivo_tg = await original.document.get_file(**tempos)
                await arquivo_tg.download_to_drive(arquivo, **tempos)
                backup = await asyncio.to_thread(instalar_banco, arquivo, config.caminho_banco)
            engine.dispose()  # descarta conexões abertas no banco antigo
        except Exception as erro:
            log.exception("Erro ao importar banco")
            await aviso.edit_text(f"😕 Não importei o banco: {erro}")
            return
        livros = listar_livros(engine)
        await aviso.edit_text(f"✅ Banco importado: {len(livros)} livros, "
                              f"{sum(c for _, c, _ in livros)} capítulos."
                              + (" (cópia do antigo guardada)" if backup else ""))

    async def pergunta(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await processar(update, update.message.text)

    async def cmd_geral(update: Update, context: ContextTypes.DEFAULT_TYPE):
        texto = " ".join(context.args)
        if not texto:
            await update.message.reply_text("Escreva a pergunta depois do comando: /geral o que é RAG?")
            return
        await processar(update, texto, forcar_geral=True)

    app = Application.builder().token(config.telegram_bot_token).build()
    app.add_handler(CommandHandler(["start", "ajuda", "help"], cmd_ajuda, filters=so_matheus))
    app.add_handler(CommandHandler("livros", cmd_livros, filters=so_matheus))
    app.add_handler(CommandHandler("livro", cmd_livro, filters=so_matheus))
    app.add_handler(CommandHandler("status", cmd_status, filters=so_matheus))
    app.add_handler(CommandHandler("proximo", cmd_proximo, filters=so_matheus))
    app.add_handler(CommandHandler("pular", cmd_pular, filters=so_matheus))
    app.add_handler(CommandHandler("pacote", cmd_pacote, filters=so_matheus))
    app.add_handler(CommandHandler("geral", cmd_geral, filters=so_matheus))
    app.add_handler(CommandHandler("importar", cmd_importar, filters=so_matheus))
    app.add_handler(CallbackQueryHandler(ao_tocar_botao))
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
