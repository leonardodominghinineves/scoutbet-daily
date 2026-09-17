# ScoutBet Diário

Bot que roda todo dia sozinho, busca os jogos do Brasileirão, manda pra IA
(Gemini, gratuito) analisar com busca na web ligada, e te envia o resultado
no Telegram. Custo: R$ 0.

## Passo a passo pra colocar no ar

### 1. football-data.org (dados dos jogos) — ✅ você já fez essa parte

### 2. Gemini (o "cérebro" que analisa) — gratuito, sem cartão
1. Entre em https://aistudio.google.com/apikey
2. Faça login com sua conta Google
3. Clique em **"Create API key"**
4. Copie a chave gerada e guarde junto com o token do football-data.org

### 3. Telegram (onde a mensagem chega)
1. Abra o Telegram, procure **@BotFather**
2. Mande `/newbot`
3. Dê um nome (ex: "ScoutBet Diário") e um username terminado em "bot"
   (ex: `scoutbet_leo_bot`)
4. Guarde o **token** que ele devolver
5. Mande "oi" pro seu bot novo (precisa ter pelo menos uma mensagem sua)
6. Pegue seu **chat_id**: abra no navegador
   `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates` (troque
   `<SEU_TOKEN>`), mande a mensagem de novo pro bot, atualize a página —
   o número em `"chat":{"id": 123456789` é o seu chat_id

### 4. GitHub (onde o robô roda de graça todo dia)
1. Crie conta em https://github.com (grátis)
2. Clique em **"New repository"**, dê um nome (ex: `scoutbet-daily`),
   deixe como privado, e crie
3. Suba estes 4 arquivos mantendo a mesma estrutura de pastas — o
   `daily.yml` tem que ficar exatamente no caminho
   `.github/workflows/daily.yml`
   - Forma mais fácil: na página do repositório, clique em
     **"Add file" → "Upload files"** e arraste os arquivos (o GitHub
     recria as pastas sozinho se você arrastar a pasta inteira)

### 5. Configurar as chaves no GitHub
1. No repositório, vá em **Settings → Secrets and variables → Actions**
2. Clique em **"New repository secret"** 4 vezes e crie:
   - `FOOTBALL_API_KEY` → o token do football-data.org
   - `GEMINI_API_KEY` → a chave do Gemini
   - `TELEGRAM_TOKEN` → o token do bot do Telegram
   - `TELEGRAM_CHAT_ID` → seu chat_id

### 6. Testar
1. Vá na aba **"Actions"** do repositório
2. Clique no workflow **"Analise diaria de apostas"** na lista à esquerda
3. Clique em **"Run workflow"** → **"Run workflow"** de novo pra confirmar
4. Espere ~1 minuto e olha seu Telegram — se a mensagem chegar, tá pronto
5. A partir daí ele roda sozinho todo dia às 08h (horário de Brasília),
   sem você precisar fazer nada

## Ajustes

- Pra trocar a liga, edite `COMPETITION_CODE` no `main.py` (ex: `"CL"` pra
  Champions League — veja os códigos em football-data.org/documentation)
- Pra mudar o horário, edite o `cron` no arquivo `.github/workflows/daily.yml`
- Se um dia o modelo `gemini-3-flash-preview` for descontinuado, troque o
  nome do modelo no `main.py` por outro da linha gratuita do Gemini
