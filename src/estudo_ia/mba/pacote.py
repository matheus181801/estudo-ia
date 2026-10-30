"""Pacote de uma aula do MBA.

Reaproveita o formato do pacote dos livros (newsletter, questões, inglês,
roteiro do vídeo, fonte do podcast) e acrescenta:
- glossário para iniciantes (o Matheus está chegando na área de tecnologia);
- conexões com os 27 livros da biblioteca (capítulos escolhidos do sumário e conferidos no código);
- avisos da aula (prazos e trabalhos), que vêm das notas.

Regra combinada: as QUESTÕES saem só do conteúdo da aula e da pesquisa web,
nunca das perguntas que os alunos fizeram em sala.
"""

from datetime import date

from pydantic import BaseModel, Field, ValidationError

from estudo_ia.config import Config
from estudo_ia.mba.filtro import NotasAula, notas_em_texto
from estudo_ia.pacote.gerador import conferir_conteudo
from estudo_ia.pacote.modelos import (ConexaoLivro, ConteudoPacote, MidiaPacote, Pacote,
                                      QuestaoMultipla, TermoGlossario)
from estudo_ia.pacote.pesquisa import ResultadoPesquisa, pesquisar_conceitos

REGRAS = """Você prepara o material de estudo do Matheus a partir de uma aula do MBA em AI Leadership.
Ele está em transição de carreira e NÃO é da área de tecnologia: conceitos básicos precisam ser
explicados do zero, sem pressupor conhecimento.

Você recebe: as notas da aula (só o conteúdo), notas de pesquisa na web sobre os mesmos conceitos
e o sumário (livros e capítulos) da biblioteca dele.

Regras obrigatórias:
- Português do Brasil; termos técnicos em inglês com a explicação ao lado.
- Explicações ORIGINAIS, com as suas palavras. Não copie trechos de nenhuma fonte.
- Use só o que está nos documentos; não invente dados, números, nomes ou estudos.
- As questões são sobre o CONTEÚDO da aula e da pesquisa web. Não use as perguntas que os alunos
  fizeram em sala como base para questões.

Tom: DIVERTIDO e leve, como um amigo que manja muito explicando num café, com analogias do
cotidiano (cozinha, futebol, trânsito, séries, games, escritório). Divertido não é infantil:
ele é um adulto num MBA, então o conteúdo continua profundo."""

PEDIDO_CONTEUDO = """Crie o pacote de estudo desta aula de {materia} (professor: {professor}):
- newsletter: título, abertura, 4 a 6 seções (cada uma com uma analogia), 5 ideias-chave,
  "na prática" (como um líder de IA usa isso no trabalho) e uma curiosidade da pesquisa web;
- glossário para iniciantes: 6 a 10 termos da aula explicados do zero;
- 5 termos de inglês técnico;
- 10 questões de múltipla escolha (4 alternativas, uma correta, comentário) e 5 abertas,
  misturando entender, aplicar e analisar, com cenários práticos; varie a posição da correta;
- conexões com os livros: 2 a 5 capítulos escolhidos SOMENTE do "Sumário da biblioteca" que
  aprofundem os conceitos da aula. Cada linha do sumário é "livro | capítulo": copie o livro e o
  capítulo exatamente como estão. Se nenhum capítulo tiver relação, deixe vazio."""

PEDIDO_MIDIA = """No mesmo tom divertido, crie para esta aula de {materia}:
- o roteiro de uma vídeo-aula de revisão: 8 a 12 slides, com narração somada entre 900 e 1.200
  palavras (cerca de 8 minutos), explicando do zero os conceitos principais;
- notas de estudo originais de 900 a 1.200 palavras, que servirão de fonte para um podcast CURTO
  e objetivo (complemento da aula, não uma aula nova)."""


class ConteudoAula(ConteudoPacote):
    glossario: list[TermoGlossario] = Field(description="6 a 10 termos explicados do zero")
    conexoes_livros: list[ConexaoLivro] = Field(description="2 a 5 itens da lista de trechos dos livros")


def sumario_biblioteca(engine) -> list[tuple[str, str]]:
    """Todos os (livro, capítulo) da biblioteca, direto do banco.

    O Claude escolhe desta lista e o código confere a escolha: assim nenhum livro
    ou capítulo é inventado. (Antes usávamos a busca do Gemini, que travava.)
    """
    from sqlmodel import select

    from estudo_ia.db import Capitulo, Livro, abrir_sessao

    with abrir_sessao(engine) as s:
        linhas = s.exec(select(Livro.titulo, Capitulo.ordem, Capitulo.titulo).join(Livro)
                        .order_by(Livro.titulo, Capitulo.ordem)).all()
    return [(livro, f"Cap. {ordem}: {cap}") for livro, ordem, cap in linhas]


def sumario_em_texto(sumario: list[tuple[str, str]]) -> str:
    return "\n".join(f"{livro} | {capitulo}" for livro, capitulo in sumario)


def conferir_conexoes(conexoes: list[ConexaoLivro], sumario: list[tuple[str, str]]) -> list[ConexaoLivro]:
    """Mantém só as conexões que existem de verdade na biblioteca."""
    validos = {(l.strip().lower(), c.strip().lower()) for l, c in sumario}
    return [c for c in conexoes if (c.livro.strip().lower(), c.capitulo.strip().lower()) in validos]


def _gerar(cliente, config: Config, documentos: list[dict], pedido: str, formato):
    try:
        with cliente.messages.stream(
            model=config.claude_modelo, max_tokens=64000, system=REGRAS,
            messages=[{"role": "user", "content": documentos + [{"type": "text", "text": pedido}]}],
            output_format=formato,
        ) as stream:
            resposta = stream.get_final_message()
    except ValidationError as erro:
        raise RuntimeError("A resposta do Claude veio incompleta (JSON cortado).") from erro
    if resposta.stop_reason in ("max_tokens", "refusal"):
        raise RuntimeError(f"O Claude não concluiu o pacote ({resposta.stop_reason}).")
    return resposta.parsed_output


def gerar_pacote_aula(cliente, config: Config, notas: NotasAula, materia: str, professor: str,
                      numero_aula: int, data_aula: date, sumario: list[tuple[str, str]],
                      revisao: list[QuestaoMultipla], avisar=print) -> Pacote:
    texto_notas = notas_em_texto(notas)

    avisar("Pesquisando os conceitos da aula na web...")
    try:
        pesquisa = pesquisar_conceitos(cliente, config, f"Notas da aula de {materia}", texto_notas)
    except Exception as erro:
        avisar(f"! Pesquisa web falhou ({type(erro).__name__}); seguindo só com a aula.")
        pesquisa = ResultadoPesquisa(notas="")

    def doc(titulo: str, texto: str, cache: bool = False) -> dict:
        bloco = {"type": "document", "title": titulo,
                 "source": {"type": "text", "media_type": "text/plain", "data": texto or "(vazio)"}}
        if cache:
            bloco["cache_control"] = {"type": "ephemeral"}  # reaproveitado na 2ª chamada
        return bloco

    documentos = [
        doc(f"Notas da aula {numero_aula} de {materia}", texto_notas),
        doc("Notas de pesquisa na web", pesquisa.notas),
        doc("Sumário da biblioteca", sumario_em_texto(sumario) or "(biblioteca vazia)", cache=True),
    ]
    formato = {"materia": materia, "professor": professor}

    avisar("Gerando newsletter, glossário e questões...")
    conteudo = _gerar(cliente, config, documentos, PEDIDO_CONTEUDO.format(**formato), ConteudoAula)
    problemas = conferir_conteudo(conteudo)
    if problemas:
        # O formato é garantido pela API, mas a quantidade não: uma nova tentativa costuma acertar.
        avisar(f"! {'; '.join(problemas)}. Gerando de novo...")
        segunda = _gerar(cliente, config, documentos, PEDIDO_CONTEUDO.format(**formato), ConteudoAula)
        if len(conferir_conteudo(segunda)) < len(problemas):
            conteudo = segunda
    avisar("Gerando roteiro do vídeo e fonte do podcast...")
    midia = _gerar(cliente, config, documentos, PEDIDO_MIDIA.format(**formato), MidiaPacote)

    return Pacote(
        tipo="aula",
        livro=materia,
        autor=professor,
        sessao_ordem=numero_aula,
        sessao_total=0,  # aulas não têm total fixo
        capitulos=[notas.titulo_aula],
        data=data_aula.isoformat(),
        conteudo=ConteudoPacote(**conteudo.model_dump(exclude={"glossario", "conexoes_livros"})),
        midia=midia,
        revisao=revisao,
        fontes_web=pesquisa.fontes,
        glossario=conteudo.glossario,
        conexoes_livros=conferir_conexoes(conteudo.conexoes_livros, sumario),
        avisos=notas.avisos,
    )
