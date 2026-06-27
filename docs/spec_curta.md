# PROMPT — VoxPrompt (versão reduzida)

Você é um engenheiro de software sênior em Python. Implemente o projeto abaixo **numa única
entrega** (plano curto no topo, depois o código completo). Para ambiguidades, decida o
razoável e comente a suposição. Só pare se houver bloqueador real.

---

## 1. Setup (faça isso primeiro)

Crie um venv e instale tudo dentro dele. Entregue um `setup.sh` com estes passos:

```bash
# deps de sistema (Ubuntu)
sudo apt install -y libportaudio2 wl-clipboard

# venv do app + deps
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install textual sounddevice soundfile openai
```

**STT local (Parakeet TDT 0.6B v3, roda na GPU):** suba um servidor OpenAI-compatible em
`localhost:8000`. Clone e instale num venv próprio (deps de PyTorch/NeMo são pesadas e
conflitam com o app):

```bash
git clone https://github.com/groxaxo/parakeet-tdt-0.6b-v3-fastapi-openai stt-server
cd stt-server
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip && pip install -r requirements.txt   # instala torch+nemo
python server.py        # baixa o modelo do HuggingFace na 1ª execução; expõe :8000/v1
```

Se a instalação do servidor falhar (CUDA/torch), documente o erro no README e siga — o app
deve funcionar no backend `openai` mesmo sem o servidor local de pé.

---

## 2. O que construir

Uma **TUI em Textual** chamada **VoxPrompt** que: grava voz → transcreve → reescreve a fala
como **pedido de engenharia estruturado** via `claude -p` → mostra na tela e copia pro
clipboard. Tudo local. Serve para ditar prompts/specs de código sem digitar.

**Comportamento (keybindings):**
- `r` — inicia/para a gravação (toggle). Mostra "● Gravando" com cronômetro.
- `s` — alterna o backend de STT: `local` (Parakeet, `http://localhost:8000/v1`,
  modelo `parakeet-tdt-0.6b-v3`) ↔ `openai` (`gpt-4o-transcribe`, usa `OPENAI_API_KEY`).
- `t` — cicla o template de reescrita: `spec` (Objetivo/Requisitos/Critérios de aceite/
  Dúvidas) → `commit` → `prompt` → `raw` (sem reescrita) → ...
- `c` — copia o resultado ativo (`wl-copy` ou `xclip`).
- `l` — re-estrutura o **último áudio** com o template atual, sem regravar.
- `q` — sair.

**Tela (Textual):** header com STT/template/status do Claude · dois painéis (transcrição
crua | pedido estruturado) · `DataTable` de histórico da sessão (índice, hora, STT, template,
preview ~60 chars, nº de chars; selecionar recarrega nos painéis) · `Footer` com as teclas ·
uma linha de status (gravando/transcrevendo/estruturando/erro).

---

## 3. Como (requisitos técnicos)

- **Não trave a UI.** Gravação, STT e `claude -p` rodam em workers de thread do Textual:
  `@work(thread=True)`, um `threading.Event` para o toggle de gravação, e
  `call_from_thread(...)` para atualizar widgets a partir da thread. O fim da gravação
  encadeia a transcrição, que encadeia a estruturação.
- **Estruturação:** chame `claude -p <instrução_do_template>` via subprocess, passando o
  texto cru por **stdin**. O env do subprocess **não pode** conter `ANTHROPIC_API_KEY`
  (usar a assinatura). Se essa var existir no ambiente, avise em vermelho no header.
  Template `raw` pula o `claude -p`.
- **Transcrição:** use o cliente `openai` para os dois backends (basta trocar `base_url` e
  `model`); `response_format="text"`.
- **Robustez:** sem rede, server local off, mic/`claude`/`xclip` ausentes → mensagem de erro
  na tela, nunca crash. Apague o WAV temporário após usar.
- **Config por env var** com defaults sensatos (`STT_BACKEND=local`, etc.).

---

## 4. Estrutura e entregáveis

```
voxprompt/
├── __main__.py     # VoxApp().run()
├── app.py          # VoxApp(App): compose, BINDINGS, actions, workers
├── config.py       # backends STT + templates + env
├── audio.py        # gravação (sounddevice/soundfile)
├── transcribe.py   # transcribe(path, backend) -> str
├── structure.py    # structure(raw, template) -> str  (claude -p)
├── clipboard.py    # copy(text) -> wl-copy|xclip
└── history.py      # HistoryEntry + SessionHistory (em memória)
```

Entregue também: `setup.sh`, `requirements.txt`, e um `README.md` com instalação, como rodar
(`python -m voxprompt`) e um smoke test de 5 passos.

Rodar: `source .venv/bin/activate && python -m voxprompt`

---

## 5. Fora do escopo

Hotkey global / injeção via ydotool · persistência em disco · qualquer UI web · streaming do
`claude -p`. Mantenha simples.