# ScoutBet — especialista em escanteios

Dois workflows no GitHub:

| Workflow | Quando roda | O que faz |
|---|---|---|
| **Relatorio diario** (`diario.yml`) | todo dia ~07:17 (Brasília) | analisa os jogos do dia nas principais ligas e manda o TOP 3 no Telegram |
| **Responder no Telegram** (`responder.yml`) | na hora em que você manda mensagem | responde perguntas e comandos em ~1 minuto |

## Como funciona (e por que as dicas agora prestam)

1. **Dados reais de escanteio** vêm da API pública da ESPN (grátis, sem chave). Ela cobre Brasileirão, Série B, Copa do Brasil, Libertadores, Sul-Americana, Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions, Europa League, Portugal, Holanda, Argentina e Championship.
2. **O cálculo é feito em Python, não pela IA.** Para cada time o modelo mede quanto ele *gera* e quanto ele *cede* de escanteios em relação à média da liga. Jogos recentes pesam mais, e amostras pequenas são puxadas para a média.
3. **Escanteios esperados** = média da liga × ataque do time × o que o adversário cede.
4. **Probabilidade de cada linha** (Over/Under total, escanteios por time, quem tem mais escanteios) pela distribuição Binomial Negativa. A variância dela é medida nos dados de cada liga.
5. **Só vira dica** quando:
   - a probabilidade fica entre 58% e 76% (odd realista),
   - os dois times têm pelo menos 6 jogos no histórico,
   - a forma dos últimos 5 jogos confirma a leitura.
6. **Odd justa = 1 ÷ probabilidade.** O bot mostra a odd mínima: se a casa pagar menos que isso, pule.
7. **A IA (Groq) só escreve 1 frase de comentário** em cima dos números, gastando poucos tokens. Se ela falhar, o bot funciona igual.
8. **Histórico:** cada dica fica salva em `data/dicas.json` e é conferida no dia seguinte (green/red).

## Passo a passo

### 1. Subir os arquivos no GitHub
Apague os arquivos antigos do repositório (`main.py`, `ask.py`, `daily.yml`, `files.zip`, `.github/workflows/main.yml` e `ask.yml`). Depois suba tudo desta pasta mantendo a estrutura: **Add file → Upload files** e arraste a pasta inteira.

### 2. Secrets (Settings → Secrets and variables → Actions → New repository secret)
- `TELEGRAM_TOKEN`: token do bot (o mesmo de antes)
- `TELEGRAM_CHAT_ID`: seu chat_id (o mesmo de antes)
- `GROQ_API_KEY`: chave do Groq (o mesmo de antes)
- *(o `FOOTBALL_API_KEY` não é mais usado, pode apagar)*

### 3. Permissão pro robô salvar o histórico
Settings → Actions → General → **Workflow permissions** → marque **Read and write permissions** → Save.

### 4. Primeiro teste
Actions → **Relatorio diario** → **Run workflow**. A primeira execução demora mais (~3–5 min) porque baixa ~8 meses de jogos. As seguintes levam ~1 min.

### 5. Resposta na hora: Cloudflare Worker (grátis)
Uma "campainha" que recebe sua mensagem no Telegram e aciona o GitHub na hora.

1. Crie um token do GitHub: **Settings → Developer settings → Fine-grained tokens → Generate**. Escolha **Only select repositories** → este repositório. Em Permissions, marque **Contents: Read and write**.
2. Crie conta em https://dash.cloudflare.com (grátis).
3. **Workers & Pages → Create → Create Worker** → dê um nome (ex: `scoutbet`) → **Deploy**.
4. **Edit code**: apague tudo, cole o conteúdo de `cloudflare/worker.js` e clique em **Deploy**.
5. No Worker, vá em **Settings → Variables and Secrets** e adicione (tipo *Secret*):
   - `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`
   - `GH_TOKEN`: o token do passo 1
   - `GH_REPO`: `seu-usuario/nome-do-repo`
   - `WEBHOOK_SECRET`: invente uma senha só com letras e números
6. Abra no navegador, uma vez:
   `https://scoutbet.SEU-SUBDOMINIO.workers.dev/setup?key=SUA_WEBHOOK_SECRET`
   Se aparecer `"ok": true`, está ligado.
7. Mande `/ajuda` pro bot.

## Comandos no Telegram
- `/hoje`: melhores apostas de hoje
- `/amanha`: melhores apostas de amanhã
- `/historico`: dicas passadas com green/red
- `/backtest`: testa o modelo nos jogos já disputados (acerto previsto × real)
- Texto livre, ex: `Flamengo x Palmeiras vale over?`, `como tá o Arsenal de escanteio?`

## Ajustes
- **Ligas:** edite `LIGAS` em `dados.py`.
- **Horário:** edite o `cron` em `.github/workflows/diario.yml`. Ele usa UTC, então 07:17 de Brasília = `17 10`.
- **Rigor das dicas:** `P_MIN`, `P_MAX` e `MIN_JOGOS` em `modelo.py`.
- **Trocar de IA** (ex: Grok da xAI): crie o secret `LLM_API_KEY` e, em *Variables*, crie `LLM_BASE_URL=https://api.x.ai/v1` e `LLM_MODEL=<modelo>`.

> Nenhum modelo garante lucro. Escanteio tem muita variância. Use o `/backtest` e o `/historico` para ver se o bot está acertando o que promete antes de aumentar a stake.
