import os
import re
from datetime import date

import requests

FOOTBALL_API_KEY = os.environ["FOOTBALL_API_KEY"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Competições cobertas pelo football-data.org gratuito (dado estruturado e confiável).
# BSA = Brasileirão | CL = Champions League | PL = Premier League
# Pra incluir mais, adicione "FL1" (Ligue 1) ou "PD" (La Liga) na lista abaixo.
COMPETITION_CODES = ["BSA", "CL", "PL"]


def get_fixtures():
    """Busca os jogos de hoje nas competições cobertas pela API estruturada."""
    today = date.today().isoformat()
    todos = []
    for code in COMPETITION_CODES:
        url = f"https://api.football-data.org/v4/competitions/{code}/matches"
        headers = {"X-Auth-Token": FOOTBALL_API_KEY}
        params = {"dateFrom": today, "dateTo": today}
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code != 200:
            # Se uma competição falhar (ex: fora de temporada), pula sem derrubar o resto
            continue
        todos.extend(resp.json().get("matches", []))
    return todos


def build_prompt(matches):
    """Monta o pedido de análise de escanteios pra IA."""
    lines = []
    for m in matches:
        home = m["homeTeam"]["name"]
        away = m["awayTeam"]["name"]
        competicao = m["competition"]["name"]
        hora = m["utcDate"]
        lines.append(f"- [{competicao}] {home} x {away} ({hora} UTC)")
    matches_text = "\n".join(lines) if lines else "(nenhum jogo hoje nas ligas cobertas)"

    return f"""Você é um especialista em escanteios de futebol, quantitativo e rigoroso.
Hoje é {date.today().isoformat()}.

Jogos de hoje:
{matches_text}

Para cada jogo, pesquise na web: média de escanteios dos últimos 5 e 10 jogos de
cada time (casa/fora, a favor/contra separadamente), estilo de jogo (cruzamentos,
finalizações, posse), perfil defensivo do adversário, desfalques em jogadores de
ponta/criação, e se conseguir, as linhas de escanteios oferecidas pelas casas de
apostas.

Método (Expected Corners):
- Ataque do time: 60% desempenho casa/fora + 40% geral
- Cruze com o perfil do adversário: time fechado/retranca tende a conceder mais
  escanteio; time que cruza muito e ataca pelas pontas gera mais que um time de
  jogo centralizado — isso pesa mais que posse de bola pura
- Forma recente: temporada/contexto 40%, últimos 10 jogos 35%, últimos 5 25%
- H2H pesa pouco, no máximo 5%

Para cada jogo, raciocine de DOIS ângulos antes de decidir:
1. Ângulo estatístico puro — só médias e Expected Corners
2. Ângulo de contexto — escalação, motivação, estilo tático específico desse confronto
Se os dois ângulos convergem (ficam próximos), a confiança é maior. Se divergem
bastante, isso é sinal de incerteza real — diga isso explicitamente.

Para cada jogo, produza:
- Expected Corners do mandante, do visitante e o total
- Intervalo provável (ex: 8 a 13)
- Probabilidade estimada só das 3-4 linhas de Over mais próximas do Expected
  Total (ex: Over 8.5, 9.5, 10.5) — não force todas as linhas
- Nível de concordância entre os dois ângulos de raciocínio: Alta / Média / Baixa
- Se tiver a odd, calcule o valor esperado (EV)

Escanteio tem MUITA variância entre jogos — só recomende quando o edge for claro
E a concordância entre os ângulos for Alta ou Média. Na dúvida, responda
"SEM EDGE CLARO" pra esse jogo. É melhor pular que forçar uma indicação fraca.
Nunca use "certeza" ou "garantido". A porcentagem de confiança precisa ser a
sua estimativa real — nunca arredonde pra cima nem exagere pra soar mais
convincente. Um "62%" honesto vale mais que um "90%" inventado.

No final, destaque no máximo 3 melhores oportunidades do dia. NUNCA responda
com uma lista crua de jogos sem análise — se não tiver dado suficiente pra
analisar um jogo, não o mencione, em vez de listar ele vazio.

Formatação (IMPORTANTE, vai direto pro Telegram como texto simples): NUNCA use
#, *, _, colchetes de citação (【】) ou qualquer símbolo de markdown. Use
emojis como marcadores e quebras de linha. Estruture cada jogo assim:

⚽ Time A x Time B
📊 Expected: X (casa Y / fora Z) — intervalo X-Y
Over 8.5: X% | Over 9.5: X% | Over 10.5: X%
🔎 Concordância: Alta/Média/Baixa

Se houver edge claro nesse jogo, adicione um bloco de destaque logo depois,
exatamente neste formato (a probabilidade tem que ser a mesma que você já
calculou acima, nunca infle o número só pra parecer mais convincente):

🎯 APOSTA DO DIA
Over [linha] escanteios — [confiança real calculada]% de chance

Se não houver edge claro, use este bloco no lugar:

🚫 SEM APOSTA CLARA — dado insuficiente ou mercado bem precificado
"""


def limpar_formatacao(texto):
    """Remove qualquer sujeira de markdown ou citação que o modelo tenha
    deixado passar, mesmo indo contra a instrução do prompt."""
    if not texto:
        return texto
    texto = re.sub(r"【[^】]*】", "", texto)  # citações tipo 【site†L12-L18】
    texto = texto.replace("**", "").replace("##", "").replace("#", "")
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def ask_groq(prompt):
    """Manda o pedido pra API gratuita do Groq, com busca na web embutida
    (modelo openai/gpt-oss-20b). Se a busca falhar por instabilidade, tenta
    de novo sem ela, pra garantir que a mensagem sempre chegue."""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    def chamar(usar_busca):
        body = {
            "model": "openai/gpt-oss-20b",
            "messages": [{"role": "user", "content": prompt}],
            "max_completion_tokens": 2048,
        }
        if usar_busca:
            body["tool_choice"] = "auto"
            body["tools"] = [{"type": "browser_search"}]
        resp = requests.post(url, headers=headers, json=body, timeout=280)
        if not resp.ok:
            print(f"Groq respondeu {resp.status_code}: {resp.text}")
        resp.raise_for_status()
        data = resp.json()
        escolhas = data.get("choices", [])
        if not escolhas:
            return None
        return (escolhas[0]["message"]["content"] or "").strip()

    try:
        resultado = chamar(usar_busca=True)
        if resultado:
            return limpar_formatacao(resultado)
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code not in (400, 429, 503, 524):
            raise  # erro diferente de instabilidade/cota, não adianta tentar de novo

    aviso = (
        "⚠️ Hoje a busca na web não estava disponível, então esta análise "
        "usa só o conhecimento geral da IA, sem dados em tempo real.\n\n"
    )
    resultado = chamar(usar_busca=False)
    return limpar_formatacao(aviso + (resultado or "Não consegui gerar a análise hoje."))


def send_telegram(text):
    """Envia a mensagem final pro seu chat do Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    text = text[:4000] if text else "Sem análise disponível hoje."
    resp = requests.post(
        url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=30
    )
    resp.raise_for_status()


def main():
    matches = get_fixtures()
    if not matches:
        send_telegram("⚽ Hoje não tem jogos nas ligas cobertas. Sem análise pra hoje.")
        return

    prompt = build_prompt(matches)
    analise = ask_groq(prompt)
    send_telegram(analise)


if __name__ == "__main__":
    main()
