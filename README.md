# VoxPrompt

TUI Linux que **grava sua voz**, **transcreve** (STT local Parakeet ou OpenAI) e
**reescreve a fala como um pedido de engenharia** via `claude -p`. Exibe transcrição
crua e resultado estruturado lado a lado, mantém histórico da sessão em memória e
copia o resultado para o clipboard.

```
┌ VoxPrompt   STT: local   Template: spec   Claude: idle ─────────────────────┐
│ ┌ Transcrição crua ───────────┐ ┌ Pedido estruturado ───────────────────┐  │
│ │ ...                         │ │ ## Objetivo ...                       │  │
│ └─────────────────────────────┘ └───────────────────────────────────────┘  │
│ # | Hora | STT | Template | Preview                          | Chars        │
│ Pronto.                                                                      │
│ r Gravar  s STT  t Template  c Copiar  l Reestruturar  h Histórico  q Sair   │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Requisitos

- **Python 3.12+**
- Pacotes de sistema:
  - `libportaudio2` — captura de microfone (`sounddevice`)
  - `wl-clipboard` (`wl-copy`, Wayland) **ou** `xclip` (X11) — copiar para o clipboard
- **`claude`** (Claude Code CLI) no `PATH` — usado para estruturar a fala
- STT, escolha um:
  - **local** (default): um servidor Parakeet OpenAI-compatible em `http://localhost:8000/v1`
  - **openai**: variável `OPENAI_API_KEY` definida

## Instalação

```bash
# dependências de sistema
sudo apt install -y libportaudio2 wl-clipboard      # ou: xclip

# ambiente Python (.venv + deps)
./setup.sh
```

`setup.sh` cria `.venv`, atualiza o `pip` e instala as dependências de `requirements.txt`.

## Rodar

```bash
source .venv/bin/activate && python -m voxprompt
```

### Atalho: alias `voxprompt` (opcional)

Para chamar a TUI de qualquer diretório digitando só `voxprompt` — sem ativar a venv.
Rode **de dentro do diretório do repositório** (após o `setup.sh`):

```bash
echo "alias voxprompt='PYTHONPATH=$(pwd) $(pwd)/.venv/bin/python -m voxprompt'" >> ~/.bashrc
source ~/.bashrc
```

O `$(pwd)` grava o caminho absoluto do seu clone no alias. Usa o Python da venv
direto (deps disponíveis) e acha o `.env` pelo caminho do módulo, não pelo diretório atual.
Em zsh, troque `~/.bashrc` por `~/.zshrc`.

## Configuração (variáveis de ambiente)

| Variável | Default | Descrição |
|---|---|---|
| `STT_BACKEND` | `local` | `local` ou `openai` |
| `OPENAI_STT_MODEL` | `gpt-4o-transcribe` | modelo STT no backend `openai` |
| `LOCAL_STT_URL` | `http://localhost:8000/v1` | base URL do servidor local OpenAI-compatible |
| `LOCAL_STT_MODEL` | `parakeet-tdt-0.6b-v3` | modelo STT local |
| `VOXPROMPT_TEMPLATE` | `spec` | template inicial (`spec`/`commit`/`prompt`/`raw`) |
| `CLAUDE_BIN` | `claude` | binário do Claude Code |
| `CLAUDE_MODEL` | `sonnet` | modelo do `claude -p` na estruturação (`sonnet`/`opus`/`haiku`). Vazio = herda o default do CLI |
| `OPENAI_API_KEY` | — | **exigido só no backend `openai`** |

> ⚠ **`ANTHROPIC_API_KEY`** não é configuração do VoxPrompt. Se estiver no ambiente,
> a TUI mostra um **alerta vermelho**: ela pode forçar `claude -p` a cobrar via API
> (billing) em vez de usar sua assinatura. O VoxPrompt **remove essa variável** do
> ambiente do subprocess `claude`, mas o alerta serve de aviso. Remova-a para garantir
> o uso do plano.

## Keybindings

| Tecla | Ação |
|---|---|
| `r` | inicia/para gravação (`● Gravando mm:ss`) |
| `s` | alterna STT `local` ↔ `openai` |
| `t` | cicla template `spec → commit → prompt → raw` |
| `c` | copia o resultado ativo para o clipboard |
| `l` | reestrutura a última transcrição com o template atual (sem regravar) |
| `h` | mostra/oculta o histórico |
| `q` | sai |

Selecionar uma linha do histórico recarrega os dois painéis.

## Templates

- **`spec`** — especificação com seções _Objetivo, Contexto, Requisitos, Critérios de aceite, Dúvidas_.
- **`commit`** — mensagem de commit (título imperativo + corpo).
- **`prompt`** — prompt direto e acionável para um agente de código.
- **`raw`** — transcrição sem reescrita (não chama o Claude).

## STT local (Parakeet)

O backend `local` espera um endpoint **OpenAI-compatible** em `LOCAL_STT_URL`
(`/audio/transcriptions`) servindo o modelo `LOCAL_STT_MODEL`
(`parakeet-tdt-0.6b-v3`). Exemplos de servidores que expõem essa interface incluem
implementações baseadas em NeMo Parakeet com camada OpenAI-compatible. Suba o servidor
em `localhost:8000` antes de gravar:

```bash
# exemplo genérico — ajuste ao seu runner de Parakeet OpenAI-compatible
your-parakeet-server --host 0.0.0.0 --port 8000 --model parakeet-tdt-0.6b-v3
```

Se o servidor estiver offline, o VoxPrompt **não trava**: mostra um erro claro na
StatusBar e segue pronto para nova tentativa.

## Modo OpenAI

```bash
export STT_BACKEND=openai
export OPENAI_API_KEY=sk-...
# opcional: export OPENAI_STT_MODEL=gpt-4o-transcribe
source .venv/bin/activate && python -m voxprompt
```

Você também pode alternar para `openai` em runtime com a tecla `s` (mas a transcrição
falhará com erro claro se `OPENAI_API_KEY` não estiver definida).

## Smoke test (5 passos)

1. **Setup**: `./setup.sh` e depois `source .venv/bin/activate`.
2. **STT**: suba o Parakeet local em `localhost:8000` **ou** `export STT_BACKEND=openai OPENAI_API_KEY=sk-...`.
3. **Abrir**: `python -m voxprompt` — a TUI abre no estado `Pronto.`.
4. **Gravar → estruturar**: pressione `r`, fale uma frase, pressione `r` de novo. O painel
   esquerdo mostra a transcrição e o direito o pedido estruturado (template `spec`); uma
   linha aparece no histórico.
5. **Copiar e sair**: pressione `c` (copia o resultado ativo), `h` (oculta/mostra histórico)
   e `q` (sai). Confira o clipboard com `wl-paste` (ou `xclip -selection clipboard -o`).

## Notas de design

- **Sem persistência em disco**: histórico vive só na memória da sessão.
- **WAV temporário** 16 kHz mono é criado por gravação e **removido após o uso** e na saída.
- **Concorrência**: gravação, STT e `claude -p` rodam em threads (`@work(thread=True)`),
  com `threading.Event` para o toggle e `call_from_thread` para atualizar a UI — a TUI
  nunca trava. Ações inválidas durante gravação/processamento são ignoradas com aviso.
- **Falhas** de microfone, rede, STT, Claude ou clipboard aparecem na StatusBar sem crash.

## Licença

MIT — veja [LICENSE](LICENSE). © 2026 Caio Rotolo.
