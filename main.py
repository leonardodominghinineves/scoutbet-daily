import os
from datetime import date

import requests

FOOTBALL_API_KEY = os.environ["FOOTBALL_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Competição: BSA = Brasileirão Série A (footballl-data.org)
# Troque por outro código se quiser acompanhar outra liga (ex: "CL" = Champions League)
COMPETITION_CODE = "BSA"


def get_fixtures():
    """Busca os jogos de hoje na competição escolhida."""
    today = date.today().isoformat()
    url = f"https://api.football-data.org/v4/competitions/{COMPETITION_CODE}/matches"
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    params = {"dateFrom": today, "dateTo": today}
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("matches", [])


def build_prompt(matches):
    """Monta o pedido de análise para a IA."""
    lines = []
    for m in matches:
        home = m["homeTeam"]["name"]
        away = m["awayTeam"]["name"]
        hora = m["utcDate"]
        lines.append(f"- {home} x {away} ({hora} UTC)")
    matches_text = "\n".join(lines)

    return f"""Você é um analista esportivo cuidadoso. Os jogos de hoje são:
{matches_text}

Para cada jogo, pesquise na web dados recentes (forma dos times, desfalques,
escalação provável, e se conseguir, odds atuais em casas de apostas conhecidas).

Depois, para cada jogo que tiver informação confiável o suficiente:
1. Dê uma estimativa de probabilidade para casa / empate / fora
2. Compare com a odds implícita de mercado, se você encontrar
3. Classifique a confiança como Alta, Média-Alta ou Média — só use "Alta"
   quando a diferença entre sua estimativa e a odds de mercado for grande
   E você tiver boa base de informação
4. No final, liste no máximo 3 recomendações no total, as de maior valor
   esperado (EV), respeitando um limite de 3 apostas por dia

Regras importantes:
- Não invente estatística. Se não achar dado confiável pra um jogo, diga
  isso e pule ele — não force uma recomendação.
- Seja honesto sobre o nível de incerteza.
- Formate a resposta pronta pra mensagem de Telegram: texto direto, pode
  usar emojis, sem tabelas ou markdown pesado.
"""


def ask_gemini(prompt):
    """Manda o pedido pra API gratuita do Gemini, com busca no Google ligada."""
    model = "gemini-3-flash-preview"  # modelo gratuito, com cota de busca generosa
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={GEMINI_API_KEY}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
    }
    resp = requests.post(url, json=body, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    candidatos = data.get("candidates", [])
    if not candidatos:
        return "Não consegui gerar a análise hoje."
    partes = candidatos[0]["content"]["parts"]
    return "\n".join(p.get("text", "") for p in partes if "text" in p).strip()


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
    if not matches:
        send_telegram("⚽ Hoje não tem jogos do Brasileirão. Sem análise pra hoje.")
        return

    prompt = build_prompt(matches)
    analise = ask_gemini(prompt)
    send_telegram(analise)


if __name__ == "__main__":
    main()
