"""Decide quem responde cada pergunta (modelo híbrido).

- Pergunta sobre o livro da trilha → Claude, que lê o livro inteiro.
- Pergunta sobre a biblioteca toda (ou sem livro na trilha) → Gemini File Search,
  que busca nos 27 livros de uma vez.
"""

from estudo_ia.bot.formatacao import normalizar

CLAUDE = "claude"
GEMINI = "gemini"

# Expressões que indicam que a pergunta vai além do livro atual.
SINAIS_GERAIS = [
    "biblioteca", "todos os livros", "outros livros", "outro livro", "nos livros",
    "entre os livros", "quais livros", "qual livro", "em geral", "compare", "comparar",
    "comparacao", "diferenca entre os autores",
]


def escolher_caminho(pergunta: str, tem_livro_ativo: bool) -> str:
    if not tem_livro_ativo:
        return GEMINI
    texto = normalizar(pergunta)
    if any(sinal in texto for sinal in SINAIS_GERAIS):
        return GEMINI
    return CLAUDE
