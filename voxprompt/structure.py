import os
import subprocess

from voxprompt.config import Config

STRUCTURE_CHUNK_CHARS = 24000

# Instruções passadas em `claude -p <instrucao>`. A transcrição vai por stdin;
# o Claude Code concatena stdin + prompt no contexto.
TEMPLATE_INSTRUCTIONS = {
    "spec": (
        "Você recebe via stdin uma transcrição de fala (possivelmente informal) de um "
        "engenheiro descrevendo um pedido. Reescreva-a como uma especificação de "
        "engenharia em português, em Markdown, com EXATAMENTE estas seções e nesta ordem: "
        "## Objetivo, ## Contexto, ## Requisitos, ## Critérios de aceite, ## Dúvidas. "
        "Seja conciso e fiel à fala; não invente requisitos. Liste em Dúvidas qualquer "
        "ambiguidade. Responda apenas com a especificação, sem preâmbulo."
    ),
    "commit": (
        "Você recebe via stdin uma transcrição de fala descrevendo uma mudança de código. "
        "Produza uma mensagem de commit em português no padrão Conventional Commits. "
        "Primeira linha: título imperativo curto (até 72 caracteres). Linha em branco. "
        "Depois um corpo explicando o quê e o porquê em tópicos. "
        "Responda apenas com a mensagem de commit, sem preâmbulo."
    ),
    "prompt": (
        "Você recebe via stdin uma transcrição de fala descrevendo uma tarefa de "
        "programação. Reescreva-a como um prompt direto e acionável para um agente de "
        "código, em português: deixe claros objetivo, restrições, arquivos/contexto "
        "relevantes e resultado esperado. Responda apenas com o prompt, sem preâmbulo."
    ),
    "financeiro": (
        "Você recebe via stdin uma transcrição de fala (possivelmente informal) descrevendo "
        "uma ideia, análise ou pedido. Reescreva-a em português com linguagem financeira "
        "profissional, empregando a terminologia correta do mercado (fluxo de caixa, margem, "
        "ROI, valuation, etc.) quando couber. Seja fiel ao conteúdo: não invente números, "
        "dados ou conclusões. Responda apenas com o texto reescrito, sem preâmbulo."
    ),
    "marketing": (
        "Você recebe via stdin uma transcrição de fala (possivelmente informal) descrevendo "
        "um produto, oferta ou ideia. Reescreva-a em português com linguagem de marketing "
        "clara e persuasiva, destacando benefícios e incluindo uma chamada para ação quando "
        "fizer sentido. Não exagere nem invente fatos. Responda apenas com o texto reescrito, "
        "sem preâmbulo."
    ),
    "formal": (
        "Você recebe via stdin uma transcrição de fala (possivelmente informal) com o "
        "conteúdo de uma mensagem. Reescreva-a como uma mensagem formal em português "
        "(e-mail profissional), com saudação, corpo claro e bem estruturado, e fechamento "
        "cordial. Eleve o registro mantendo a intenção da fala. Responda apenas com a "
        "mensagem, sem preâmbulo."
    ),
    "whatsapp": (
        "Você recebe via stdin uma transcrição de fala (possivelmente informal) com o "
        "conteúdo de uma mensagem. Reescreva-a como uma mensagem informal de WhatsApp em "
        "português: tom leve e direto, frases curtas e emojis com moderação quando couber. "
        "Mantenha a intenção da fala. Responda apenas com a mensagem, sem preâmbulo."
    ),
    "conversa": (
        "Você recebe via stdin uma conversa transcrita a partir de vários áudios curtos, "
        "em ordem cronológica, com um bloco por arquivo. Produza uma saída em Markdown "
        "com EXATAMENTE estas seções e nesta ordem: ## Transcrição em ordem, ## Resumo, "
        "## Pendências. Em Transcrição em ordem, limpe vícios de linguagem e repetições "
        "excessivas sem resumir nem cortar conteúdo; preserve a ordem dos áudios, horários "
        "e rótulos de falante recebidos. Se o falante estiver como 'não identificado pelo "
        "arquivo', mantenha essa informação e não invente Eu/Cliente. Em Resumo, liste os "
        "principais pontos conversados. Em Pendências, liste ações, dúvidas e próximos "
        "passos mencionados; escreva 'Nenhuma pendência identificada.' se não houver. "
        "Responda apenas com as seções pedidas, sem preâmbulo."
    ),
    "reuniao": (
        "Você recebe via stdin a transcrição bruta de uma reunião em português. Produza a "
        "saída em Markdown com EXATAMENTE estas duas partes, nesta ordem.\n\n"
        "## Transcrição limpa\n"
        "Reproduza TODO o conteúdo da reunião fielmente, sem cortar, resumir nem omitir "
        "nenhum ponto discutido. Esta parte é transcrição, não síntese - jamais a resuma. "
        "Remova APENAS: vícios de linguagem ('então', 'tipo', 'né', 'assim', 'é', "
        "hesitações), repetições excessivas da mesma frase e ruídos de fala sem conteúdo. "
        "Mantenha a voz de cada participante, a ordem cronológica e todos os detalhes ditos.\n\n"
        "## Consolidado da reunião\n"
        "Baseie-se apenas no que foi dito na reunião, sem inferências. Use estas subseções:\n"
        "### Decisões tomadas\n"
        "Liste o que foi definido ou aprovado durante a reunião.\n"
        "### Próximos passos\n"
        "Liste as ações identificadas, com responsável e prazo quando mencionados.\n"
        "### Pontos em aberto\n"
        "Liste dúvidas ou temas que ficaram sem resolução; omita a lista se não houver.\n\n"
        "Nenhum conteúdo da Transcrição limpa pode ser apagado para 'caber' no Consolidado. "
        "Responda apenas com as duas partes, sem preâmbulo."
    ),
}

REUNIAO_CLEAN_CHUNK_INSTRUCTION = (
    "Você recebe via stdin UM BLOCO de uma transcrição bruta de reunião em português. "
    "Limpe somente este bloco e responda apenas com a transcrição limpa do bloco, sem "
    "título. Reproduza TODO o conteúdo fielmente, sem cortar, resumir nem omitir nenhum "
    "ponto discutido. Remova apenas vícios de linguagem, hesitações, repetições excessivas "
    "da mesma frase e ruídos de fala sem conteúdo. Mantenha participantes, ordem "
    "cronológica e detalhes."
)

REUNIAO_CONSOLIDATE_INSTRUCTION = (
    "Você recebe via stdin a Transcrição limpa completa de uma reunião. Produza apenas o "
    "Consolidado da reunião em Markdown, baseado somente no que foi dito, sem inferências. "
    "Use estas subseções: ### Decisões tomadas, ### Próximos passos, ### Pontos em aberto. "
    "Omita listas vazias. Não inclua a seção Transcrição limpa."
)


class StructureError(RuntimeError):
    """Falha ao estruturar via `claude -p` (binário ausente, timeout, returncode != 0)."""


def split_text_chunks(text: str, max_chars: int | None = None) -> list[str]:
    """Divide texto longo em blocos aproximados, preservando quebras de linha."""
    max_chars = STRUCTURE_CHUNK_CHARS if max_chars is None else max_chars
    if max_chars <= 0:
        raise ValueError("max_chars deve ser positivo")
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > max_chars:
            if current:
                chunks.append(current.rstrip())
                current = ""
            chunks.append(line[:max_chars].rstrip())
            line = line[max_chars:]

        if current and len(current) + len(line) > max_chars:
            chunks.append(current.rstrip())
            current = ""
        current += line

    if current:
        chunks.append(current.rstrip())
    return [chunk for chunk in chunks if chunk]


def structure(text: str, template: str, config: Config) -> str:
    """`raw` retorna a transcrição como veio. Os demais chamam `claude -p`.

    Remove ANTHROPIC_API_KEY do ambiente do subprocess para não forçar billing via API.
    Textos curtos preservam o fluxo antigo; textos longos são processados em blocos.
    """
    if template == "raw":
        return text

    instruction = TEMPLATE_INSTRUCTIONS.get(template)
    if instruction is None:
        raise StructureError(f"Template desconhecido: {template!r}")

    chunks = split_text_chunks(text)
    if len(chunks) == 1:
        return _run_claude(text, instruction, config)
    if template == "reuniao":
        return _structure_long_reuniao(chunks, config)
    return _structure_long_generic(chunks, instruction, template, config)


def _structure_long_generic(
    chunks: list[str], instruction: str, template: str, config: Config
) -> str:
    partial_instruction = (
        f"{instruction}\n\n"
        "Você está processando apenas um bloco de uma transcrição longa. Preserve os "
        "fatos e ambiguidades deste bloco; não invente informações para preencher lacunas."
    )
    partials = [
        _run_claude(chunk, partial_instruction, config)
        for chunk in chunks
    ]
    final_instruction = (
        f"Você recebe via stdin resultados parciais do template {template!r}, gerados a "
        "partir de blocos sequenciais da mesma transcrição. Consolide em uma única saída "
        "final coerente, remova duplicações entre blocos e preserve apenas informações "
        "presentes nos parciais. Responda apenas com o resultado final, sem preâmbulo.\n\n"
        f"Instrução original do template: {instruction}"
    )
    return _run_claude("\n\n--- BLOCO ---\n\n".join(partials), final_instruction, config)


def _structure_long_reuniao(chunks: list[str], config: Config) -> str:
    clean_chunks = [
        _run_claude(chunk, REUNIAO_CLEAN_CHUNK_INSTRUCTION, config)
        for chunk in chunks
    ]
    clean_transcript = "\n\n".join(clean_chunks).strip()
    consolidated = _run_claude(
        clean_transcript, REUNIAO_CONSOLIDATE_INSTRUCTION, config
    ).strip()
    consolidated = _strip_heading(consolidated, "## Consolidado da reunião")
    return (
        "## Transcrição limpa\n"
        f"{clean_transcript}\n\n"
        "## Consolidado da reunião\n"
        f"{consolidated}"
    ).strip()


def _strip_heading(text: str, heading: str) -> str:
    stripped = text.strip()
    if stripped.lower().startswith(heading.lower()):
        return stripped[len(heading):].strip()
    return stripped


def _run_claude(text: str, instruction: str, config: Config) -> str:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)

    cmd = [config.claude_bin]
    if config.claude_model:
        cmd += ["--model", config.claude_model]
    cmd += ["-p", instruction]

    try:
        proc = subprocess.run(
            cmd,
            input=text,
            capture_output=True,
            text=True,
            env=env,
            timeout=config.claude_timeout_sec,
        )
    except FileNotFoundError as exc:
        raise StructureError(
            f"Binário '{config.claude_bin}' não encontrado (instale o Claude Code)."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise StructureError(
            f"claude excedeu o tempo limite ({config.claude_timeout_sec}s)."
        ) from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise StructureError(f"claude falhou (código {proc.returncode}): {detail}")

    output = (proc.stdout or "").strip()
    if not output:
        raise StructureError("claude retornou saída vazia.")
    return output
