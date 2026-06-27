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
