# TODO: empacotamento + entry point `voxprompt`

Status: **pendente** (decidido adiar; por ora usa-se o alias no `~/.bashrc` — ver README).

## Objetivo

Permitir instalar o VoxPrompt como pacote e expor o comando `voxprompt` nativamente
(sem alias e sem `python -m voxprompt`), tanto para o uso local quanto para terceiros
que clonem o repositório open-source.

## O que fazer

1. Adicionar `pyproject.toml` (PEP 621) com:
   - `[project]`: `name = "voxprompt"`, `version`, `description`, `requires-python = ">=3.12"`,
     `dependencies` (mover de `requirements.txt`), `license = "MIT"`.
   - `[project.scripts]`: `voxprompt = "voxprompt.app:main"` → cria o executável no `bin/` do ambiente.
   - Incluir o asset `voxprompt/voxprompt.tcss` no pacote (package-data / `[tool.setuptools.package-data]`).
2. `pip install -e .` na venv → vira `voxprompt` em `.venv/bin/voxprompt`.
3. Atualizar README: substituir a seção do alias pela instrução `pip install -e .` (o alias
   continua válido como alternativa rápida sem instalar).
4. (Opcional) Publicar no PyPI: `python -m build` + `twine upload`, ou distribuir via `pipx install`.

## Notas

- `requirements.txt` pode virar um pin de runtime ou ser substituído pelas `dependencies` do pyproject.
- Confirmar que o `.env` continua sendo lido: hoje `config._load_dotenv()` resolve o caminho por
  `Path(__file__).parent.parent / ".env"`. Num install instalado (não-editável) isso aponta para o
  site-packages, não para o cwd — avaliar trocar para procurar o `.env` no diretório atual
  (`find_dotenv()` / cwd) quando empacotado.
- Manter `python -m voxprompt` funcionando (não remover o `__main__.py`).
