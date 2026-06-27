import os
import subprocess

from voxprompt.config import Config

CLAUDE_TIMEOUT_SEC = 120

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
    "reuniao": (
        "Você recebe via stdin a transcrição bruta de uma reunião em português. Produza a "
        "saída em Markdown com EXATAMENTE estas duas partes, nesta ordem.\n\n"
        "## Transcrição limpa\n"
        "Reproduza TODO o conteúdo da reunião fielmente, sem cortar, resumir nem omitir "
        "nenhum ponto discutido. Esta parte é transcrição, não síntese — jamais a resuma. "
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


class StructureError(RuntimeError):
    """Falha ao estruturar via `claude -p` (binário ausente, timeout, returncode != 0)."""


def structure(text: str, template: str, config: Config) -> str:
    """`raw` retorna a transcrição como veio. Os demais chamam `claude -p`.

    Remove ANTHROPIC_API_KEY do ambiente do subprocess para não forçar billing via API.
    """
    if template == "raw":
        return text

    instruction = TEMPLATE_INSTRUCTIONS.get(template)
    if instruction is None:
        raise StructureError(f"Template desconhecido: {template!r}")

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
            timeout=CLAUDE_TIMEOUT_SEC,
        )
    except FileNotFoundError as exc:
        raise StructureError(
            f"Binário '{config.claude_bin}' não encontrado (instale o Claude Code)."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise StructureError(
            f"claude excedeu o tempo limite ({CLAUDE_TIMEOUT_SEC}s)."
        ) from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise StructureError(f"claude falhou (código {proc.returncode}): {detail}")

    output = (proc.stdout or "").strip()
    if not output:
        raise StructureError("claude retornou saída vazia.")
    return output
