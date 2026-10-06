# Pipeline BDTD — Instruções Drive Shared (Equipe)

> **Objetivo:** subir `data/raw` (PDFs + manifestos) para Shared Drive com **deduplicação por conteúdo** (nenhum arquivo duplicado entra, mesmo com nome diferente).

---

## 1. Credenciais — o que cada membro precisa

| Item | Onde pegar | Valor |
|------|------------|-------|
| `GDRIVE_FOLDER_ID` | Drive link `https://drive.google.com/drive/u/0/folders/1UImdu0YmqoPd8ulwHfDUIMaHBAuIq_N8` | `1UImdu0YmqoPd8ulwHfDUIMaHBAuIq_N8` |
| `Shared Drive` | Nome no Drive à esquerda | já contém a pasta acima |
| `SA JSON` **ou** OAuth | Ver seções 1A / 1B | `~/.config/pipeline-bdtd/sa-key.json` |
| Acesso ao Drive | Owner adiciona seu email | `Gerenciador de conteúdo` no Shared Drive |

**Owner (admin do Drive) — 1x:**
`drive.google.com > Shared drives > (drive) > Gerenciar membros > Adicionar > email@da.pessoa > Gerenciador de conteúdo`. Para muitas pessoas, crie `Grupo Google` e adicione o Grupo.

---

### 1A. Opção SA (usada neste repo) — Service Account `drive-bdtd`
- **SA:** `pipeline-drive-bdtd@drive-bdtd.iam.gserviceaccount.com` (ID `117446805467169387494`, projeto `drive-bdtd`)
- **Policy desativada:** `iam.disableServiceAccountKeyCreation` desabilitada para `drive-bdtd` em `console.cloud.google.com/iam-admin/orgpolicies/iam-disableServiceAccountKeyCreation/edit?project=drive-bdtd` (feito, rastreamento `c6297743439299186`).
- **JSON:** `secrets/drive-bdtd-sa.json` (não commitado, `.gitignore:155` `secrets/` + `*.json`). Cópia segura em `~/.config/pipeline-bdtd/sa-key.json` (`chmod 600`).
- **Drive API:** habilitada em `console.cloud.google.com/apis/library/drive.googleapis.com` para `drive-bdtd`.

**Para cada membro (SA compartilhada):**
```bash
mkdir -p ~/.config/pipeline-bdtd
# peça a SA JSON ao owner via canal seguro (1Password/Vault), NÃO por Git/Email aberto
cp /caminho/para/drive-bdtd-sa.json ~/.config/pipeline-bdtd/sa-key.json
chmod 600 ~/.config/pipeline-bdtd/sa-key.json
```

### 1B. Opção OAuth (sem SA key — alternativa se org bloquear de novo)
- Criar `Tela de consentimento OAuth` + `ID cliente OAuth > App para computador` em `drive-bdtd` -> baixa `client_secret.json` -> cada membro roda `drive-sync` 1x e autoriza no browser -> gera `token.json` pessoal.

---

## 2. Instalação

```bash
# na raiz do repo
uv sync
# .env (copie de .env.example)
cp .env.example .env
# edite .env:
# GOOGLE_APPLICATION_CREDENTIALS=~/.config/pipeline-bdtd/sa-key.json
# GDRIVE_FOLDER_ID=1UImdu0YmqoPd8ulwHfDUIMaHBAuIq_N8
# (GDRIVE_SHARED_DRIVE_ID opcional)

# verifique
uv run python -c "from remote.drive import build_drive_client; print(build_drive_client())"
```

---

## 3. Como usar — Upload com dedup

```bash
# dry-run: lista o que seria enviado sem enviar
uv run python main.py drive-sync --layer raw --dry-run
# envia raw (padrão) com dedup por sha256
uv run python main.py drive-sync --layer raw
# envia várias camadas
uv run python main.py drive-sync --layer raw --layer curated
# pasta específica / workers
uv run python main.py drive-sync --folder-id 1UImdu0YmqoPd8ulwHfDUIMaHBAuIq_N8 --workers 4
# mostra dedup: "3 duplicados (sha256)" = arquivos com conteúdo já no Drive (mesmo de outro usuário)
```

**Dedup:** cada arquivo tem `sha256` calculado localmente e comparado com `appProperties.sha256` de TODO o Drive (recursivo). Mesmo hash em path diferente = `duplicate` (não envia). Mesmo path+hash = `skipped`. Isso vale para uploads concorrentes de múltiplos usuários.

**R2 ainda funciona:** `uv run python main.py sync --layer raw --bucket meu-bucket` inalterado.

---

## 4. Migração R2 -> Drive (o que estava no Cloudflare para o Drive)

```bash
# dry-run da migração
uv run python main.py migrate-r2-to-drive --prefix raw --dry-run
# migra de fato (baixa do R2, recalcula sha256, dedup, sobe ao Drive)
uv run python main.py migrate-r2-to-drive --prefix raw --workers 4
# outro prefix
uv run python main.py migrate-r2-to-drive --prefix curated
```

Usa `GOOGLE_APPLICATION_CREDENTIALS` + `R2_*` do `.env`. Temporários em `tmp` auto-limpo.

---

## 5. Segurança — NÃO faça

- ❌ Commitar `*.json` / `*.pem` / `secrets/*` / `important.txt` (`.gitignore:155` já bloqueia)
- ❌ Mandar SA JSON por Slack/Email aberto
- ❌ Deixar `drive-bdtd-sa.json` na raiz do repo (mover para `~/.config/...` ou `secrets/` local)
- ✅ Revogar: `IAM e administrador > Contas de serviço > pipeline-drive-bdtd > Chaves > Excluir` + gerar nova

---

## 6. Troubleshooting

| Erro | Causa | Solução |
|------|-------|---------|
| `GOOGLE_APPLICATION_CREDENTIALS not found` | path errado | `ls -l ~/.config/pipeline-bdtd/sa-key.json` + `export` |
| `403 drive.files.list` | SA não é membro do Shared Drive | Owner adiciona SA como Gerenciador de conteúdo |
| `rateLimitExceeded` | muitos workers | `--workers 2` |
| `iam.disableServiceAccountKeyCreation` | policy reativada | usar OAuth (1B) ou admin desativa para `drive-bdtd` |

---

## 7. IDs FIXOS deste projeto

- **Folder ID alvo:** `1UImdu0YmqoPd8ulwHfDUIMaHBAuIq_N8` (`https://drive.google.com/drive/u/0/folders/1UImdu0YmqoPd8ulwHfDUIMaHBAuIq_N8`)
- **SA:** `pipeline-drive-bdtd@drive-bdtd.iam.gserviceaccount.com`
- **Comandos:** `main.py drive-sync`, `main.py migrate-r2-to-drive`, `main.py sync` (R2 legado)
