import os
from datetime import date

import requests

FOOTBALL_API_KEY = os.environ["FOOTBALL_API_KEY"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Competições cobertas pelo football-data.org gratuito (dado estruturado e confiável).
# BSA = Brasileirão | CL = Champions League | PL = Premier League
# FL1 = Ligue 1 | PD = La Liga
COMPETITION_CODES = ["BSA", "CL", "PL", "FL1", "PD"]

# Libertadores e Sul-Americana não existem no plano gratuito do football-data.org,
# então pedimos pro Gemini procurar esses jogos direto na web.
COMPETICOES_VIA_WEB = ["Copa Libertadores", "Copa Sul-Americana"]


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
    """Monta o pedido de análise para a IA."""
    lines = []
    for m in matches:
        home = m["homeTeam"]["name"]
        away = m["awayTeam"]["name"]
        competicao = m["competition"]["name"]
        hora = m["utcDate"]
        lines.append(f"- [{competicao}] {home} x {away} ({hora} UTC)")
    matches_text = "\n".join(lines) if lines else "(nenhum jogo encontrado nas ligas com dado estruturado)"

    competicoes_web = ", ".join(COMPETICOES_VIA_WEB)

    return f"""Você é um analista esportivo cuidadoso. Hoje é {date.today().isoformat()}.

Jogos confirmados (dado estruturado):
{matches_text}

Além desses, pesquise na web se hoje tem jogos de: {competicoes_web}.
Se encontrar, inclua na análise. Se não encontrar nenhum jogo dessas competições
hoje, não invente — apenas não mencione.

Para CADA jogo (dos confirmados acima e dos que você achar via busca), pesquise
na web dados recentes: forma dos times, desfalques, escalação provável, e se
conseguir, odds atuais em casas de apostas conhecidas.

Para cada jogo com informação confiável o suficiente, produza:
1. Mercado de resultado (casa/empate/fora): sua estimativa de probabilidade,
   comparada com a odds implícita de mercado se encontrar
2. Mercado de gols (over/under 2.5): sua estimativa, baseada no histórico
   recente de gols marcados/sofridos dos dois times
3. Mercado de escanteios — use esta metodologia:
   - Calcule Expected Corners do mandante e do visitante combinando: ataque
     da equipe (peso maior no mando: 60% casa/fora + 40% geral) e escanteios
     concedidos pelo adversário nesse mesmo contexto
   - Pondere forma recente assim: temporada/contexto 40%, últimos 10 jogos
     35%, últimos 5 jogos 25% — nunca decida só pelos últimos 5
   - Head-to-head tem peso baixo (máximo 5%), nunca deixe H2H antigo dominar
   - Estime probabilidade para as linhas de Over/Under mais próximas do
     Expected Total (geralmente entre 8.5 e 11.5), sem forçar todas as linhas
   - Se tiver odd disponível, calcule EV = (probabilidade × odd) - 1
   - Só aponte uma recomendação de escanteios quando houver EDGE real (diferença
     relevante entre sua probabilidade estimada e a implícita na odd). Se a
     amostra for insuficiente, os dados forem conflitantes, ou a diferença for
     pequena, responda "SEM EDGE CLARO" para esse jogo — não force indicação
   - Nunca use "certeza" ou "garantido"
4. Um nível de confiança por mercado analisado: Alta, Média-Alta ou Média —
   só use "Alta" quando a diferença entre sua estimativa e a odds de mercado
   for grande E você tiver boa base de informação

No final, liste no máximo 3 recomendações no total (juntando todos os jogos e
mercados), as de maior valor esperado (EV), respeitando um limite de 3 apostas
por dia.

Regras importantes:
- Não invente estatística, principalmente em escanteios, que tem menos dado
  público. Se não achar dado confiável pra um mercado, diga isso e pule ele.
- Seja honesto sobre o nível de incerteza.
- Formate a resposta pronta pra mensagem de Telegram: texto direto, pode
  usar emojis, sem tabelas ou markdown pesado.
"""


def ask_groq(prompt):
    """Manda o pedido pra API gratuita do Groq, com busca na web embutida
    (modelo openai/gpt-oss-20b). Se a busca falhar, tenta de novo sem ela,
    pra garantir que a mensagem sempre chegue."""
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
            body["tool_choice"] = "required"
            body["tools"] = [{"type": "browser_search"}]
        resp = requests.post(url, headers=headers, json=body, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        escolhas = data.get("choices", [])
        if not escolhas:
            return None
        return (escolhas[0]["message"]["content"] or "").strip()

    try:
        resultado = chamar(usar_busca=True)
        if resultado:
            return resultado
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code not in (429, 503):
            raise  # erro diferente de cota/instabilidade, não adianta tentar de novo

    aviso = (
        "⚠️ Hoje a busca na web não estava disponível, então esta análise "
        "usa só o conhecimento geral da IA, sem dados em tempo real.\n\n"
    )
    resultado = chamar(usar_busca=False)
    return aviso + (resultado or "Não consegui gerar a análise hoje.")


def send_telegram(text):
    """Envia a mensagem final pro seu chat do Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    # Telegram limita ~4096 caracteres por mensagem
    text = text[:4000] if text else "Sem análise disponível hoje."
    resp = requests.post(
        url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=30
    )
    resp.raise_for_status()


def main():
    matches = get_fixtures()
    prompt = build_prompt(matches)
    analise = ask_groq(prompt)
    send_telegram(analise)


if __name__ == "__main__":
    main()
