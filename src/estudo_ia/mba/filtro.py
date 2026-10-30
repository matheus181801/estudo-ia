"""Filtro da aula: transforma slides + transcrição em notas só com o conteúdo.

A transcrição de 3 horas tem muita coisa que não é conteúdo: combinados
(câmera, intervalo), brincadeiras, relatos pessoais de colegas. O Claude lê
tudo e devolve as "notas da aula": o que o professor ensinou, com os
exemplos dele, e as perguntas de alunos que ajudam a entender o tema.

As notas são a base de todo o resto (pacote, podcast, vídeo, perguntas no bot).
"""

from pydantic import BaseModel, Field, ValidationError

from estudo_ia.config import Config

INSTRUCOES = """Você recebe o material (slides) e a transcrição de uma aula de MBA em AI Leadership.
Na transcrição, "Professor" é o professor e "Aluno" é qualquer aluno.

Sua tarefa é escrever as NOTAS DA AULA, só com o conteúdo:
- Inclua: conceitos, explicações, frameworks, exemplos e casos que o professor apresentou,
  e o que está nos slides. Seja detalhado: as notas substituem assistir à aula de novo.
- Inclua perguntas de alunos SOMENTE quando ajudam a entender o conteúdo, resumidas e com a
  resposta do professor.
- Exclua: combinados e logística (câmera, microfone, intervalo, chamada), brincadeiras,
  conversa paralela, relatos pessoais e opiniões de alunos sem relação com o conteúdo.
- NUNCA escreva nomes de alunos, empresas onde os alunos trabalham ou detalhes pessoais deles.
  O nome do professor pode aparecer.
- Prazos, trabalhos, provas e entregas mencionados vão SÓ na lista "avisos".
- Escreva em português do Brasil, com as suas palavras; termos técnicos em inglês com a explicação.
- Não invente nada que não esteja nos slides ou na fala do professor."""


class TopicoAula(BaseModel):
    titulo: str
    explicacao: str = Field(description="O que foi ensinado, em detalhes (2 a 6 parágrafos)")
    exemplos: list[str] = Field(description="Exemplos e casos citados pelo professor neste tópico")


class PerguntaRelevante(BaseModel):
    pergunta: str = Field(description="A dúvida do aluno, resumida, sem nome")
    resposta: str = Field(description="O que o professor respondeu")


class NotasAula(BaseModel):
    titulo_aula: str = Field(description="Título curto que resume o tema da aula")
    resumo: str = Field(description="Resumo da aula em 3 a 5 frases")
    topicos: list[TopicoAula] = Field(description="6 a 12 tópicos, na ordem da aula")
    perguntas_relevantes: list[PerguntaRelevante]
    conceitos_chave: list[str] = Field(description="5 a 10 conceitos centrais (termos curtos)")
    avisos: list[str] = Field(description="Prazos, trabalhos, provas ou entregas mencionados (pode ser vazio)")


def notas_em_texto(notas: NotasAula) -> str:
    """Versão em texto corrido das notas, usada como fonte nas próximas etapas."""
    partes = [f"# {notas.titulo_aula}", notas.resumo]
    for t in notas.topicos:
        partes.append(f"## {t.titulo}\n{t.explicacao}")
        partes += [f"- Exemplo: {e}" for e in t.exemplos]
    if notas.perguntas_relevantes:
        partes.append("## Perguntas da turma")
        partes += [f"P: {p.pergunta}\nR: {p.resposta}" for p in notas.perguntas_relevantes]
    return "\n\n".join(partes)


def extrair_notas(cliente, config: Config, materia: str, professor: str,
                  texto_material: str, transcricao_anonima: str) -> NotasAula:
    try:
        with cliente.messages.stream(
            model=config.claude_modelo,
            max_tokens=64000,
            system=INSTRUCOES,
            messages=[{"role": "user", "content": [
                {"type": "document", "title": f"Slides da aula de {materia}",
                 "source": {"type": "text", "media_type": "text/plain", "data": texto_material or "(sem slides)"}},
                {"type": "document", "title": f"Transcrição da aula (professor: {professor})",
                 "source": {"type": "text", "media_type": "text/plain", "data": transcricao_anonima}},
                {"type": "text", "text": "Escreva as notas desta aula seguindo as regras."},
            ]}],
            output_format=NotasAula,
        ) as stream:
            resposta = stream.get_final_message()
    except ValidationError as erro:
        raise RuntimeError("As notas da aula vieram incompletas (JSON cortado).") from erro
    if resposta.stop_reason in ("max_tokens", "refusal"):
        raise RuntimeError(f"Não consegui gerar as notas da aula ({resposta.stop_reason}).")
    return resposta.parsed_output
