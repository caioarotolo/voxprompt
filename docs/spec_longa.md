# SPEC / PROMPT (SDD) — VoxPrompt: TUI de voz → pedido de engenharia

> Cole este documento inteiro no `/goal` do Claude Code ou no Codex.
> É uma especificação dirigida (Spec-Driven Development) pensada para implementação
> **one-shot**: o agente produz um plano curto e, na mesma resposta, implementa o projeto
> inteiro seguindo esta spec.

---

## 0. Instruções para o agente

Você é um engenheiro de software sênior em Python. Implemente o sistema abaixo seguindo a
spec à risca.

1. Comece a resposta com um **plano de implementação curto** (lista de arquivos + ordem).
2. **Na mesma resposta**, implemente o projeto completo. NÃO pare para pedir aprovação.
3. Para qualquer ambiguidade, aplique as **Decisões travadas (§12)** e registre a suposição
   num comentário no código. Só interrompa se houver um bloqueador real (ex.: dependência
   impossível de instalar).
4. Implemente em módulos coesos, testáveis isoladamente, e entregue tudo de uma vez.
5. Ao final, inclua: comando de instalação, comando de execução, e um checklist de smoke test.

Existe um script v1 (`voice_to_prompt.py`) que já faz o pipeline básico (gravar →
transcrever com backend OpenAI/local → `claude -p` → clipboard). **Refatore-o** nesta
arquitetura Textual, **preservando** a lógica de duplo backend de STT e do `claude -p`.

---

## 0.5. Pré-requisitos do ambiente (o usuário garante antes de rodar)

Estes itens já estarão prontos na máquina; assuma que existem:

- Python 3.11+ e `pip`.
- Sistema Linux (Ubuntu/Wayland alvo; X11 suportado). `libportaudio2` instalável via apt.
- Clipboard: `wl-copy` (Wayland) ou `xclip` (X11) disponível.
- Binário `claude` instalado e autenticado em modo assinatura (`claude login`), **sem**
  `ANTHROPIC_API_KEY` no ambiente.
- (Para STT local) servidor Parakeet OpenAI-compatible rodando em `http://localhost:8000/v1`.
- (Para STT via API) `OPENAI_API_KEY` exportado.

O agente deve, ainda assim, **degradar com elegância** se algum item faltar (mensagem de
erro na TUI, nunca crash) — ver RNF2.

---

## 1. Objetivo

Uma aplicação de terminal (TUI em **Textual**) chamada **VoxPrompt** que captura voz,
transcreve, reescreve a fala como um **pedido de engenharia estruturado** via `claude -p`,
e exibe tudo numa interface interativa com histórico de sessão. Tudo local.

Caso de uso: ditar prompts/specs de código sem digitar, e ter o texto já limpo e
estruturado para colar no Cursor/Claude Code/terminal.

---

## 2. Escopo

**Dentro do escopo:**
- Captura de áudio do microfone.
- Transcrição com backend selecionável: OpenAI API ou Parakeet local (OpenAI-compatible).
- Estruturação via `claude -p` com template de prompt selecionável.
- TUI em Textual: header de status, painéis de transcrição crua e resultado, tabela de
  histórico, indicadores ao vivo (cronômetro de gravação, spinner de processamento).
- Interação por keybindings (Textual `BINDINGS` → `action_*`).
- Cópia do resultado para o clipboard.
- Histórico **da sessão** (em memória).

**Fora do escopo (NÃO implementar):**
- Hotkey global / injeção de texto via ydotool (fase futura).
- Persistência de histórico em disco entre sessões.
- Qualquer UI web / chatbot (é o Projeto 2).
- Streaming token-a-token do `claude -p` (resposta completa basta nesta versão).

---

## 3. Requisitos funcionais

**RF1 — Gravação (toggle por tecla).** A tecla `r` inicia a gravação; `r` de novo encerra.
Durante a gravação, a TUI mostra indicador "● Gravando" com cronômetro (segundos decorridos,
atualizado via `set_interval`). A gravação roda em **worker de thread** para não travar a UI
(ver §4.3).

**RF2 — Transcrição.** Ao encerrar, envia o áudio para o backend STT ativo e obtém o texto
cru. Dois backends, selecionáveis em runtime:
- `openai`: modelo `gpt-4o-transcribe` (default) via API. Requer `OPENAI_API_KEY`.
- `local`: endpoint OpenAI-compatible (Parakeet TDT 0.6B v3) em `LOCAL_STT_URL`
  (default `http://localhost:8000/v1`), modelo `LOCAL_STT_MODEL` (default `parakeet-tdt-0.6b-v3`).
A transcrição roda em worker de thread; ao terminar, encadeia a estruturação.

**RF3 — Estruturação.** Envia o texto cru para `claude -p` (subprocess), passando o texto
cru por **stdin** e a instrução do template ativo como argumento `-p`. Captura a saída como
o "pedido estruturado". O env do subprocess **não** pode conter `ANTHROPIC_API_KEY`. Também
roda em worker de thread.

**RF4 — Templates de prompt.** 4 templates selecionáveis em runtime (tecla `t` cicla):
- `spec` (default): Objetivo / Contexto / Requisitos / Critérios de aceite / Dúvidas em aberto.
- `commit`: mensagem de commit (título imperativo + corpo).
- `prompt`: prompt direto e conciso para um agente de código.
- `raw`: sem reescrita — passa a transcrição crua direto (pula o `claude -p`).

**RF5 — Cópia.** Tecla `c` copia o resultado ativo para o clipboard via `wl-copy` ou
`xclip` (detectar qual existe). Indicar sucesso/falha na TUI.

**RF6 — Re-estruturar.** Tecla `l` reprocessa o **último áudio transcrito** com o template
atual, **sem regravar** (reaproveita o texto cru). Permite trocar de `spec` para `commit`
no mesmo conteúdo.

**RF7 — Histórico da sessão.** Cada ciclo (gravação→resultado) vira uma linha numa
`DataTable` do Textual: índice, horário, backend STT, template, preview do resultado
(~60 chars), contagem de chars. Selecionar uma linha (setas + Enter, ou clique) recarrega
seu conteúdo nos painéis.

**RF8 — Status de auth.** No header, indicar se o `claude` está disponível e em modo
assinatura. Se `ANTHROPIC_API_KEY` estiver setado no ambiente, **avisar em vermelho** que o
billing irá para API paga.

---

## 4. Especificação da TUI (Textual)

### 4.1. Layout (widgets)

```
┌─ VoxPrompt ──────────────────────────────────────────────┐
│ STT: local · Template: spec · Claude: ✓ assinatura        │  ← Header custom (Static)
├──────────────────────────┬───────────────────────────────┤
│ Transcrição crua         │ Pedido estruturado            │  ← 2 painéis (RichLog/TextArea)
│ ...                      │ ...                           │     em Horizontal container
├──────────────────────────┴───────────────────────────────┤
│ Histórico (DataTable)                                     │
│ #  hora    STT     template  preview            chars     │
│ 1  14:02   local   spec      "Implementar o..."  412      │
├───────────────────────────────────────────────────────────┤
│ ● Gravando 00:03   /   Transcrevendo… (spinner)           │  ← StatusBar (Static reativo)
└───────────────────────────────────────────────────────────┘
   Footer com keybindings (widget Footer nativo)
```

- Use `compose()` com containers (`Horizontal`/`Vertical`) e estilização via CSS do Textual
  (arquivo `voxprompt.tcss` ou `CSS` inline).
- Header e StatusBar como `Static` ligados a **reactive attributes** (atualizam sozinhos ao
  mudar estado).
- Painéis: `TextArea` (read-only) ou `RichLog` — escolha do agente, justifique.
- Histórico: `DataTable`.
- Footer: widget `Footer` nativo, que renderiza os `BINDINGS` automaticamente.

### 4.2. Keybindings (BINDINGS → action_*)

| Tecla | Action | Efeito |
|---|---|---|
| `r` | `toggle_record` | inicia/para gravação |
| `s` | `switch_stt` | alterna backend STT (openai ↔ local) |
| `t` | `cycle_template` | cicla template (spec→commit→prompt→raw→spec) |
| `c` | `copy_result` | copia resultado ativo |
| `l` | `restructure` | re-estrutura último áudio com template atual |
| `h` | `toggle_history` | mostra/oculta a DataTable |
| `q` | `quit` | sair |

Durante gravação/processamento, desabilite as ações que não façam sentido (ou ignore-as com
um aviso na StatusBar).

### 4.3. Padrão de concorrência (REQUISITO — seguir este desenho)

Gravação e chamadas de STT/`claude -p` são bloqueantes; rode-as em **workers de thread** do
Textual para a UI não congelar. Use `@work(thread=True)`, um `threading.Event` para o
toggle de gravação, e `self.call_from_thread(...)` para tocar widgets a partir da thread.

Referência de arquitetura (o agente deve seguir esse padrão):

```python
from textual.app import App
from textual import work
import threading, queue, tempfile, os
import sounddevice as sd, soundfile as sf

class VoxApp(App):
    BINDINGS = [
        ("r", "toggle_record", "Gravar/Parar"),
        ("s", "switch_stt", "Trocar STT"),
        ("t", "cycle_template", "Template"),
        ("c", "copy_result", "Copiar"),
        ("l", "restructure", "Re-estruturar"),
        ("h", "toggle_history", "Histórico"),
        ("q", "quit", "Sair"),
    ]

    def __init__(self):
        super().__init__()
        self._recording = threading.Event()

    def action_toggle_record(self) -> None:
        if self._recording.is_set():
            self._recording.clear()        # sinaliza parada
        else:
            self.record_audio()            # dispara o worker

    @work(thread=True, exclusive=True)
    def record_audio(self) -> None:
        self._recording.set()
        path = tempfile.mktemp(suffix=".wav")
        q = queue.Queue()
        cb = lambda indata, *a: q.put(indata.copy())
        with sf.SoundFile(path, "w", samplerate=16000, channels=1) as f:
            with sd.InputStream(samplerate=16000, channels=1, callback=cb):
                self.call_from_thread(self.set_status, "● Gravando")
                while self._recording.is_set():
                    f.write(q.get())
        self.transcribe_audio(path)         # parou → encadeia transcrição

    @work(thread=True)
    def transcribe_audio(self, path: str) -> None:
        self.call_from_thread(self.set_status, "Transcrevendo…")
        raw = transcribe(path, self.stt_backend)       # função do Projeto 1
        self.call_from_thread(self.show_raw, raw)
        self.structure_text(raw)                        # encadeia estruturação
        os.unlink(path)

    @work(thread=True)
    def structure_text(self, raw: str) -> None:
        self.call_from_thread(self.set_status, "Estruturando…")
        result = structure(raw, self.template)          # função do Projeto 1 (claude -p)
        self.call_from_thread(self.show_result, result)
        self.call_from_thread(self.add_history, raw, result)
        self.call_from_thread(self.set_status, "Pronto")
```

O cronômetro de gravação: `set_interval(1, self._tick)` atualizando um reactive enquanto
`self._recording.is_set()`.

### 4.4. Estados visuais

- Idle / Gravando (cronômetro) / Transcrevendo (spinner) / Estruturando (spinner) / Erro
  (linha vermelha na StatusBar, sem derrubar a app).

---

## 5. Requisitos não-funcionais

**RNF1 — Segurança de billing.** Subprocess do `claude -p` roda com env onde
`ANTHROPIC_API_KEY` está ausente. Se detectado no ambiente do processo, header em vermelho.

**RNF2 — Robustez.** Falha de rede (OpenAI), server local off, `claude`/`xclip`/mic ausentes
→ mensagem de erro na StatusBar/painel, nunca crash.

**RNF3 — Sem bloqueio da UI.** Toda operação bloqueante em `@work(thread=True)` (§4.3); a UI
segue renderizando spinner/cronômetro.

**RNF4 — Arquivos temporários.** WAV temporário por gravação; apagar após uso e ao sair.

**RNF5 — Config via env + defaults sensatos.** Tudo por env var, com defaults que funcionam
out-of-the-box no modo `local`.

**RNF6 — Linux-first.** Ubuntu/Wayland alvo; X11 via `xclip`. Python 3.11+.

---

## 6. Stack e dependências

- `textual` — framework da TUI (já traz o `rich` como dependência).
- `sounddevice` + `soundfile` — captura de áudio (requer `libportaudio2`).
- `openai` — cliente para ambos os backends STT (OpenAI e local OpenAI-compatible).
- Dependências de sistema (externas): binário `claude`, `wl-copy`/`xclip`.
- Sem framework web, sem banco de dados. NÃO usar `readchar`/`prompt_toolkit` (o Textual
  cobre keybindings).

Entregar um `requirements.txt` (ou `pyproject.toml`) e o `.tcss` se usar CSS em arquivo.

---

## 7. Estrutura de módulos (alvo)

```
voxprompt/
├── __main__.py        # entry point: monta config e roda VoxApp().run()
├── app.py             # VoxApp(App): compose(), BINDINGS, actions, workers (§4.3)
├── config.py          # CONFIG de backends STT, templates de prompt, env vars
├── audio.py           # gravação de baixo nível (sounddevice/soundfile) reusável
├── transcribe.py      # transcribe(path, backend) -> texto cru
├── structure.py       # structure(raw, template) -> texto estruturado (claude -p / raw)
├── clipboard.py       # copy(text) -> wl-copy|xclip
├── history.py         # HistoryEntry + SessionHistory (lista em memória)
├── widgets.py         # (opcional) Header/StatusBar custom como Static reativo
└── voxprompt.tcss     # (opcional) estilos do Textual
```

`app.py` concentra o estado/UI; `transcribe.py`, `structure.py`, `audio.py`, `clipboard.py`
são serviços sem estado global (reutilizáveis no Projeto 2).

---

## 8. Modelo de dados

```python
@dataclass
class HistoryEntry:
    id: int
    timestamp: datetime
    stt_backend: str        # "openai" | "local"
    template: str           # "spec" | "commit" | "prompt" | "raw"
    raw_text: str
    structured_text: str
    duration_sec: float     # duração do áudio gravado
```

`SessionHistory` mantém `list[HistoryEntry]`; expõe `add()`, `get(index)`, `latest()`.

---

## 9. Configuração (env vars)

| Var | Default | Uso |
|---|---|---|
| `STT_BACKEND` | `local` | backend STT inicial |
| `OPENAI_API_KEY` | — | obrigatório se backend `openai` |
| `OPENAI_STT_MODEL` | `gpt-4o-transcribe` | modelo do backend openai |
| `LOCAL_STT_URL` | `http://localhost:8000/v1` | endpoint Parakeet |
| `LOCAL_STT_MODEL` | `parakeet-tdt-0.6b-v3` | modelo local |
| `VOXPROMPT_TEMPLATE` | `spec` | template inicial |
| `CLAUDE_BIN` | `claude` | caminho do binário claude |

`ANTHROPIC_API_KEY` não é configuração — se presente, é alerta (RNF1).

---

## 10. Critérios de aceite (testáveis)

- [ ] `python -m voxprompt` abre a TUI Textual sem erro (header, painéis, histórico, footer).
- [ ] `r` grava e para; cronômetro aparece e atualiza durante a gravação; UI não congela.
- [ ] Transcreve nos dois backends; `s` alterna; backend ativo visível no header.
- [ ] `t` cicla os 4 templates; ativo aparece no header.
- [ ] Template `spec` produz as seções; `raw` pula o `claude -p` e mostra a transcrição crua.
- [ ] `c` copia o resultado ativo; colar em outro app traz o texto.
- [ ] `l` re-estrutura o último áudio com o template atual sem regravar.
- [ ] Cada ciclo adiciona uma linha na DataTable; selecionar recarrega nos painéis.
- [ ] Com `ANTHROPIC_API_KEY` setada, header em vermelho.
- [ ] Erros (sem rede, server local off, sem mic) viram mensagem na TUI, sem crash.
- [ ] WAVs temporários removidos.
- [ ] README com instalação, execução e smoke test.

---

## 11. Plano de entrega (milestones internos do agente)

1. **M1 — Serviços headless:** `audio.py`, `transcribe.py`, `structure.py`, `clipboard.py`,
   `config.py`, `history.py` (refatorados do v1), testáveis por uma `main()` simples.
2. **M2 — App Textual estática:** `app.py` com `compose()` e widgets exibindo dados mock.
3. **M3 — Workers + fluxo:** `BINDINGS`/actions ligados aos workers (§4.3): gravar→transcrever
   →estruturar→exibir, com cronômetro e spinner.
4. **M4 — Histórico:** `DataTable` populada, seleção recarrega painéis, `l` re-estrutura.
5. **M5 — Robustez/polish:** erros, status de auth, limpeza de temporários, CSS, README.

Implemente todos numa única entrega.

---

## 12. Decisões travadas (aplicar; não reabrir)

- **Framework:** Textual (não Rich+readchar, não prompt_toolkit, não urwid).
- **Gravação:** toggle por tecla `r` (NÃO usar VAD/parada por silêncio nesta versão).
- **Concorrência:** workers de thread do Textual (`@work(thread=True)`) + `threading.Event`
  + `call_from_thread` (padrão da §4.3). Não usar asyncio puro para o áudio bloqueante.
- **STT local:** Parakeet TDT 0.6B v3 via endpoint OpenAI-compatible em `localhost:8000`.
- **STT API:** `gpt-4o-transcribe`.
- **Estruturação:** `claude -p` via subprocess + stdin, usando a assinatura (sem API key).
- **Sem streaming** do `claude -p` nesta versão (resposta completa).
- **Histórico:** em memória, só na sessão; preview de 60 chars.
- **Painéis read-only:** `TextArea` (read-only) ou `RichLog` — escolha do agente, justifique
  em 1 linha.

Fim da spec.