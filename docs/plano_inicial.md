# Plano: Chat UI local com switch STT + Claude/Codex pela assinatura

Objetivo: rodar uma UI de chat open source em `localhost`, adaptada para (1) alternar a transcrição entre API (OpenAI) e STT local (Parakeet na RTX 4060), e (2) usar Claude e Codex como "cérebros" do chat **pela sua assinatura**, não pela API paga.

---

## 1. Visão geral da arquitetura

```
┌─────────────────────────────────────────────┐
│  Chat UI (better-chatbot, Next.js)  :3000    │
│  - seletor de "modelo": Claude / Codex / ... │
│  - botão de voz com switch STT (API | local) │
└───────────────┬──────────────┬───────────────┘
                │              │
       (provider OpenAI-compatible)
                │              │
        ┌───────▼──────┐  ┌────▼─────────┐
        │ Adapter LLM  │  │ Adapter STT  │
        │ (FastAPI)    │  │ (/v1/audio/  │
        │ /v1/chat/... │  │  transcr.)   │
        └──┬────────┬──┘  └──┬────────┬──┘
           │        │        │        │
      claude -p   codex   Parakeet  OpenAI
    (Agent SDK)   exec    (local)   (API)
      assinatura  assin.  GPU       paga
```

A ideia central: **escondemos `claude -p` e `codex exec` atrás de endpoints HTTP compatíveis com a API da OpenAI.** Assim a UI (que já fala "OpenAI-compatible") acha que está conversando com um modelo normal, mas por baixo está shellando para os CLIs oficiais, que autenticam pela sua assinatura. Mesma técnica vale para o STT: um endpoint `/v1/audio/transcriptions` local que, por dentro, chama Parakeet ou repassa para a OpenAI.

---

## 2. Escolha da UI base

**Recomendado: better-chatbot (cgoinglove / "Navigator").**
- Stack: Next.js + Vercel AI SDK + Postgres (Drizzle) + Better Auth.
- Já é multi-provider e cliente MCP, com assistente de voz realtime embutido.
- Aceita providers OpenAI-compatible (já suporta Ollama/OpenRouter), então adicionar um "provider custom" apontando para nosso adapter é o caminho natural.

Alternativa mais enxuta: **Vercel ai-chatbot** (template oficial). Mais simples/minimalista, bom se você quer menos features e mais controle do zero. Tem menos coisa pronta (sem MCP/voz nativo), então daria mais trabalho para o switch de voz.

Decisão: começar pelo better-chatbot. Se achar pesado, migrar a lógica de adapter para o template da Vercel (os adapters são independentes da UI).

---

## 3. Plugar Claude e Codex pela assinatura (o núcleo)

### 3.1. Regras de ouro (billing + ToS)

- **Claude:** NÃO extrair o token OAuth para bater na API direto — isso viola os Termos de Consumo (política de credenciais de fev/2026). O caminho permitido é **shellar para o binário oficial `claude -p`** ou usar o **Claude Agent SDK oficial**, que autentica pelo login do Claude Code.
- Desde 15/06/2026, `claude -p` / Agent SDK consomem um **crédito mensal separado** do Agent SDK (US$20 Pro / US$100 Max 5x / US$200 Max 20x), não o pool interativo. Não acumula; quando esgota, para (ou cai em créditos de API, se habilitado).
- **NUNCA** setar `ANTHROPIC_API_KEY` no ambiente do backend — isso força cobrança via API paga.
- **Codex:** caminho headless oficial é `codex exec`, autenticando via `~/.codex/auth.json` (login ChatGPT). Consome a cota da sua assinatura ChatGPT. NÃO setar `OPENAI_API_KEY` no ambiente do Codex (faria ele usar API paga). Atenção: o mesmo `OPENAI_API_KEY` é usado pelo STT da OpenAI — por isso os adapters devem rodar com ambientes separados (ver 3.4).

### 3.2. Adapter do Claude (`claude -p`)

Servidor FastAPI expondo `POST /v1/chat/completions` (formato OpenAI). Por dentro:
1. Recebe `messages[]`.
2. Monta o prompt (system + histórico) — pode passar o histórico via stdin e a instrução via `-p`.
3. Executa `claude -p <prompt> --output-format stream-json` (ou texto simples) via subprocess.
4. Faz streaming da saída de volta como SSE no formato `chat.completion.chunk`.

Pontos de atenção:
- Use `--output-format stream-json` se quiser streaming token a token; senão, `--output-format text` e devolve de uma vez.
- Defina `--allowed-tools` / `--permission-mode` conforme o quanto quer que ele aja (só responder vs. mexer em arquivos).
- Garanta que o processo herda o login do Claude Code (`claude login` feito antes, sem `ANTHROPIC_API_KEY`).
- Alternativa "mais limpa": usar o **Claude Agent SDK (Python)** em vez de subprocess — mesma autenticação, API programática melhor (`claude-agent-sdk`).

### 3.3. Adapter do Codex (`codex exec`)

Mesmo padrão: FastAPI com `POST /v1/chat/completions`. Por dentro:
1. `codex exec --full-auto <prompt>` (ou modo read-only se for só pra responder).
2. Para conversas multi-turno, usar `codex exec resume` / `--last` para continuar a sessão.
3. Streamar a saída de volta.

Alternativa via MCP: rodar `codex mcp` (Codex como servidor MCP stdio) e conectá-lo ao better-chatbot como **ferramenta**. Bom se você quer o Codex como sub-agente acionável por @menção, em vez de "modelo principal" do chat. Pode coexistir com o adapter HTTP.

### 3.4. Isolamento de ambiente (importante)

Como `ANTHROPIC_API_KEY` e `OPENAI_API_KEY` mudam o comportamento de billing, rode cada adapter com env limpo:
- Adapter Claude: sem `ANTHROPIC_API_KEY`. Login feito via `claude login` (assinatura).
- Adapter Codex: sem `OPENAI_API_KEY`. Login via `codex login` (ChatGPT).
- Adapter/uso do STT OpenAI: ESTE sim usa `OPENAI_API_KEY`, mas deve estar em um processo separado do Codex.
- Recomendo subir cada adapter como um serviço próprio (systemd user service ou processos separados), cada um com seu env file.

### 3.5. Registrar como "modelos" na UI

No better-chatbot, adicione providers custom OpenAI-compatible:
- Provider "Claude (assinatura)" → base_url `http://localhost:8811/v1`, modelo `claude-cli`.
- Provider "Codex (assinatura)" → base_url `http://localhost:8812/v1`, modelo `codex-cli`.
- A `api_key` pode ser qualquer string (os adapters ignoram).

Aí o seletor de modelo da UI já vira seu switch entre Claude, Codex e qualquer outro provider real.

---

## 4. O switch de STT (Parakeet local vs OpenAI API)

### 4.1. Servidor Parakeet local (OpenAI-compatible)

- Use o repo `groxaxo/parakeet-tdt-0.6b-v3-fastapi-openai` (FastAPI que expõe Parakeet TDT 0.6B v3 com contrato OpenAI em `/v1/audio/transcriptions`).
- Sobe em `localhost:8000/v1`. Roda na RTX 4060 (precisa de ~2GB VRAM).
- Parakeet v3 é multilíngue (inclui PT/ES/EN) com detecção automática de idioma.
- Alternativa: faster-whisper large-v3 atrás de um servidor OpenAI-compatible (ex.: `speaches`/`faster-whisper-server`) se quiser mais cobertura/robustez.

### 4.2. Roteador de STT

Opção A (mais simples): um pequeno proxy `/v1/audio/transcriptions` que, conforme um header/flag (`X-STT-Backend: local|openai`), repassa para `localhost:8000` (Parakeet) ou para `api.openai.com` (gpt-4o-transcribe). A UI manda o flag conforme o estado do switch.

Opção B: a UI chama direto um dos dois base_urls conforme o toggle, sem proxy. Menos código, mas espalha a lógica no front.

### 4.3. Adaptar o front

- No componente de voz do better-chatbot, adicionar um toggle "STT: Local | API".
- Captura de áudio no browser (MediaRecorder) → manda o blob para o endpoint de transcrição escolhido → texto cai no input do chat.
- O assistente de voz realtime nativo do better-chatbot usa a Realtime API da OpenAI; para STT local você provavelmente vai usar o fluxo "gravar → transcrever → inserir texto" (não o realtime), então trate como dois modos distintos de voz.

---

## 5. Passo a passo de execução (por fases)

**Fase 0 — Pré-requisitos**
- Node 20+, pnpm, Docker (Postgres), Python 3.11+, CUDA toolkit para a 4060.
- `claude login` (assinatura, sem ANTHROPIC_API_KEY) e `codex login` (ChatGPT).
- Testar `claude -p "oi"` e `codex exec "oi"` no terminal e confirmar via `/status` que estão em modo assinatura.

**Fase 1 — Subir a UI base**
- Clonar better-chatbot, configurar `.env` (Postgres via `pnpm docker:pg`, Better Auth secret), rodar local em `:3000`. Validar com um provider real qualquer (ex.: um modelo OpenAI normal) só pra ver a UI funcionando.

**Fase 2 — STT local**
- Subir o servidor Parakeet (`:8000`). Testar transcrição via curl com um wav.
- Reaproveitar/adaptar seu script `voice_to_prompt.py` para validar o endpoint.

**Fase 3 — Switch de STT no front**
- Adicionar o toggle Local|API no componente de voz e o fluxo gravar→transcrever→inserir.

**Fase 4 — Adapter do Claude**
- FastAPI `:8811` shellando `claude -p`. Testar via curl no formato OpenAI. Registrar como provider na UI.

**Fase 5 — Adapter do Codex**
- FastAPI `:8812` shellando `codex exec`. Testar e registrar. (Opcional: `codex mcp` como tool.)

**Fase 6 — Polimento**
- Streaming (SSE) nos adapters, tratamento de erro/limite de cota, histórico multi-turno, e empacotar tudo como serviços (systemd user) pra subir com um comando.

---

## 6. Riscos e armadilhas

- **Cota do Agent SDK (Claude):** o pool mensal separado pode esgotar rápido em uso pesado. Monitorar.
- **ToS do Claude:** ficar no `claude -p`/Agent SDK oficial. Não extrair/reusar token OAuth fora do Claude Code.
- **Vazamento de env:** um `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` esquecido no shell faz o billing trocar silenciosamente para API paga. Isolar ambientes.
- **Streaming e multi-turno via CLI:** CLIs são feitos para sessão de terminal; mapear histórico de chat para chamadas stateless/resume dá trabalho. Comece sem streaming e sem histórico longo, evolua.
- **Latência:** cada chamada sobe um processo CLI. Para uso pessoal tá ok; não é arquitetura de produção multiusuário.
- **Versões mudam:** flags de `claude -p` e `codex exec`, nomes de pacote (Claude Code SDK → Claude Agent SDK) e política de billing mudaram em 2026. Confirmar a doc vigente antes de cada fase.

---

## 7. Stack final / serviços

| Serviço | Porta | Auth | Billing |
|---|---|---|---|
| better-chatbot (UI) | 3000 | Better Auth | — |
| Postgres | 5432 | — | — |
| Parakeet STT | 8000 | nenhuma | grátis (local/GPU) |
| Adapter Claude (`claude -p`) | 8811 | login Claude Code | crédito Agent SDK (assinatura) |
| Adapter Codex (`codex exec`) | 8812 | login ChatGPT | cota ChatGPT (assinatura) |
| (opcional) Proxy STT | 8800 | — | API só quando "API" selecionado |

---

## Resumo de uma linha

Esconda `claude -p` e `codex exec` atrás de endpoints OpenAI-compatible para usar a assinatura como "modelos" da UI; faça o mesmo com o STT (Parakeet local vs OpenAI) atrás de `/v1/audio/transcriptions`; o better-chatbot vira só a casca que orquestra os switches.