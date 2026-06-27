# Roadmap — Voz → Código com Claude (2 projetos)

Dois projetos encadeados. O **Projeto 1** é o script standalone (voz → transcrição → `claude -p` estrutura como pedido de engenharia). O **Projeto 2** é a evolução: acoplar essa lógica dentro de uma UI de chat tipo better-chatbot, com switches de STT e de modelo (Claude/Codex pela assinatura).

---

# PROJETO 1 — Script "voz vira pedido de engenharia"

CLI simples e local. Você fala, ele transcreve, o `claude -p` reescreve como pedido técnico limpo e estruturado, e copia pro clipboard. Já temos o `voice_to_prompt.py` pronto — este projeto é só fechar o setup e validar.

## 1.1. O que faz (pipeline)

```
🎙️ grava áudio (ENTER pra parar)
   └─► 📝 transcreve  ──► [ backend: OpenAI API | Parakeet local ]
        └─► 🤖 claude -p reescreve como pedido de engenharia (assinatura)
             └─► 📋 imprime + copia pro clipboard
```

## 1.2. Decisões já tomadas

- **Transcrição:** dois backends via env var `STT_BACKEND`:
  - `openai` → `gpt-4o-transcribe` (ou `gpt-4o-mini-transcribe`, mais barato). ~US$0,006/min. Precisa de `OPENAI_API_KEY`.
  - `local` → Parakeet TDT 0.6B v3 na RTX 4060 (multilíngue PT/ES/EN, ~2GB VRAM, grátis/offline), exposto via endpoint OpenAI-compatible em `localhost:8000/v1`.
- **Limpeza/estruturação:** `claude -p` (shell para o binário oficial), usando o crédito do Agent SDK incluído na assinatura. **Sem** `ANTHROPIC_API_KEY` no ambiente.
- **Saída:** clipboard via `wl-copy` (Wayland) ou `xclip` (X11).

## 1.3. Passo a passo de execução

**A. Dependências**
```bash
pip install openai sounddevice soundfile
sudo apt install libportaudio2 wl-clipboard   # ou xclip no X11
```

**B. Auth (sem vazar API key do Claude)**
```bash
claude login            # login da assinatura
unset ANTHROPIC_API_KEY # garantir que não força API paga
claude -p "oi"          # smoke test
```

**C. Modo API (rápido pra validar)**
```bash
export OPENAI_API_KEY="sk-..."
python voice_to_prompt.py
```

**D. Modo local (Parakeet)**
1. Clonar e subir `groxaxo/parakeet-tdt-0.6b-v3-fastapi-openai` (expõe `localhost:8000/v1`).
2. Validar com curl/um wav de teste.
3. Rodar:
```bash
export STT_BACKEND=local
python voice_to_prompt.py
```

## 1.4. Melhorias opcionais (depois)

- **Hotkey global + injeção de texto:** envolver com `ydotool` e um atalho do DE para virar um "Wispr de verdade" — ativa de qualquer app e o texto cai direto no Cursor/terminal (em vez de só copiar).
- **Variações de prompt:** ter 2-3 instruções (spec, commit message, prompt pro Claude) e escolher por flag.
- **Forçar idioma:** descomentar `language="pt"` se a auto-detecção tropeçar.

## 1.5. Critério de "pronto"

- [ ] Transcreve nos dois backends (API e local).
- [ ] `claude -p` reescreve usando a assinatura (confirmado via `/status`, sem cobrança de API).
- [ ] Texto estruturado cai no clipboard.
- [ ] (Opcional) Hotkey global funcionando.

---

# PROJETO 2 — Acoplar no chatbot (better-chatbot)

Evolução do Projeto 1: em vez de um CLI isolado, a mesma lógica vira parte de uma UI de chat local. Os switches viram elementos de interface, e Claude/Codex entram como "modelos" do chat usando a assinatura.

## 2.1. O que muda em relação ao Projeto 1

| | Projeto 1 | Projeto 2 |
|---|---|---|
| Interface | CLI (terminal) | UI web em `localhost:3000` |
| STT switch | env var `STT_BACKEND` | toggle na UI (Local \| API) |
| Claude | só limpeza de texto | "modelo" do chat (conversa) |
| Codex | — | "modelo" do chat ou tool MCP |
| Histórico | nenhum | persistido (Postgres) |

## 2.2. Arquitetura

```
┌──────────────────────────────────────────────┐
│  better-chatbot (Next.js)  :3000             │
│  - seletor de modelo: Claude | Codex | ...   │
│  - voz com toggle STT: Local | API           │
└──────────┬──────────────────┬────────────────┘
           │ (providers OpenAI-compatible)
   ┌───────▼───────┐   ┌───────▼────────┐
   │ Adapter Claude│   │ Adapter Codex  │
   │ FastAPI :8811 │   │ FastAPI :8812  │
   │  claude -p    │   │  codex exec    │
   └───────────────┘   └────────────────┘
           │ STT
   ┌───────▼────────────────────────────┐
   │ Parakeet :8000  |  OpenAI API       │
   │ /v1/audio/transcriptions            │
   └─────────────────────────────────────┘
```

Princípio: **esconder `claude -p` e `codex exec` atrás de endpoints compatíveis com a API da OpenAI**, para a UI tratá-los como modelos normais. O STT reaproveita 100% o que foi feito no Projeto 1.

## 2.3. Regras de billing/ToS (reforço)

- **Claude:** só `claude -p` / Agent SDK oficial. NUNCA extrair/reusar o token OAuth fora do Claude Code (viola ToS). Usa o crédito mensal do Agent SDK (incluído na assinatura, com teto que não acumula).
- **Codex:** `codex exec` com login ChatGPT (`~/.codex/auth.json`), consome a cota do plano. Incluído nos planos pagos.
- **Isolar ambientes:** o adapter do Claude não pode ter `ANTHROPIC_API_KEY`; o do Codex não pode ter `OPENAI_API_KEY` (esse fica só no caminho do STT OpenAI, em processo separado).

## 2.4. Passo a passo de execução (por fases)

**Fase 0 — Pré-requisitos**
- Node 20+, pnpm, Docker (Postgres), Python 3.11+, CUDA para a 4060.
- `claude login` e `codex login` (ambos em modo assinatura, sem API keys no ambiente).
- Confirmar `claude -p "oi"` e `codex exec "oi"` funcionando pela assinatura.

**Fase 1 — Subir a UI**
- Clonar better-chatbot, `.env` (Postgres via `pnpm docker:pg`, Better Auth secret), rodar em `:3000`.
- Validar com um provider real qualquer só pra ver a UI de pé.

**Fase 2 — STT (reaproveita Projeto 1)**
- Subir Parakeet (`:8000`). Já validado no Projeto 1.
- (Opcional) proxy `/v1/audio/transcriptions` que roteia Local|API por header.

**Fase 3 — Toggle STT no front**
- Botão "STT: Local | API" no componente de voz.
- Fluxo: MediaRecorder grava → manda blob pro endpoint escolhido → texto cai no input.
- Nota: o assistente de voz realtime nativo do better-chatbot usa a Realtime API da OpenAI; o STT local é o modo "gravar → transcrever → inserir". Tratar como dois modos distintos.

**Fase 4 — Adapter Claude (`:8811`)**
- FastAPI expondo `POST /v1/chat/completions` que shella `claude -p`.
- Começar sem streaming e sem histórico longo; evoluir depois.
- Registrar como provider custom na UI (base_url `http://localhost:8811/v1`, api_key qualquer).

**Fase 5 — Adapter Codex (`:8812`)**
- Mesmo padrão com `codex exec`. Para multi-turno, usar `codex exec resume`/`--last`.
- Alternativa: `codex mcp` como ferramenta acionável por @menção (decidir: modelo vs tool).

**Fase 6 — Polimento**
- Streaming (SSE) nos adapters, tratamento de cota esgotada, histórico multi-turno.
- Empacotar Parakeet + adapters como systemd user services (sobe tudo com um comando).

## 2.5. Riscos a vigiar

- Cota do Agent SDK (Claude) pode esgotar em uso pesado — não acumula, renova no ciclo.
- Env vazado (`ANTHROPIC_API_KEY`/`OPENAI_API_KEY`) troca billing pra API paga silenciosamente.
- Mapear chat multi-turno para CLIs stateless dá trabalho — começar simples.
- Latência: cada chamada sobe um processo CLI. OK para uso pessoal, não para multiusuário.
- Flags e billing mudam rápido em 2026 — conferir doc vigente antes de cada fase.

## 2.6. Critério de "pronto"

- [ ] UI de pé em `localhost:3000` com histórico persistido.
- [ ] Toggle STT Local|API funcionando na voz.
- [ ] Claude selecionável como modelo, respondendo pela assinatura.
- [ ] Codex selecionável (como modelo ou tool), respondendo pela assinatura.
- [ ] Nenhum vazamento de API key forçando billing pago.

---

## Ordem recomendada

1. Fechar o **Projeto 1** inteiro (inclusive Parakeet local) — ele entrega valor sozinho e já resolve o STT do Projeto 2.
2. Só então partir pro **Projeto 2**, fase a fase, validando cada adapter via curl antes de plugar na UI.

O Projeto 1 é a fundação reutilizável; o Projeto 2 é a casca que orquestra os switches em volta dele.