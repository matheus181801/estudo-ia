"""Botões do bot (teclados "inline", que aparecem embaixo da mensagem).

Cada botão carrega um texto curto escondido (callback_data, até 64 bytes)
que volta para o bot quando o Matheus toca nele. Usamos prefixos:
- "livro:16"  → escolher o livro 16
- "comecar"   → gerar e entregar o pacote agora
- "amanha"    → esperar a entrega automática das 06:00
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from estudo_ia.ingestao.biblioteca import listar_livros
from estudo_ia.trilha import planejador

LIMITE_TITULO = 48  # botões muito longos ficam cortados no celular


def rotulo_livro(titulo: str, ativo: bool, progresso: tuple[int, int] | None) -> str:
    """Texto do botão: ▶️ no livro atual, ✅ nos terminados, n/total nos começados."""
    titulo = titulo if len(titulo) <= LIMITE_TITULO else titulo[: LIMITE_TITULO - 1] + "…"
    if progresso:
        feitas, total = progresso
        marca = "✅" if feitas >= total else f"{feitas}/{total}"
        titulo = f"{titulo} · {marca}"
    return f"▶️ {titulo}" if ativo else titulo


def teclado_livros(engine) -> InlineKeyboardMarkup:
    ativo, progresso = planejador.progresso_por_livro(engine)
    linhas = [
        [InlineKeyboardButton(rotulo_livro(livro.titulo, livro.id == ativo, progresso.get(livro.id)),
                              callback_data=f"livro:{livro.id}")]
        for livro, _, _ in listar_livros(engine)
    ]
    return InlineKeyboardMarkup(linhas)


def teclado_comecar() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🚀 Começar agora", callback_data="comecar"),
        InlineKeyboardButton("⏰ Amanhã às 6h", callback_data="amanha"),
    ]])
