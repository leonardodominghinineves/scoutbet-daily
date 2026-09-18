import os

import requests

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

MODEL = "gemini-flash-latest"

# Metodologia completa de escanteios (usada quando a pergunta é sobre esse mercado)
METODOLOGIA_ESCANTEIOS = """Você é um analista especialista em escanteios de futebol. Seja
quantitativo, conservador, e evite conclusões baseadas em uma única estatística.

Regras principais:
- Calcule Expected Corners combinando ataque da equipe (peso 60% no
  mando/fora + 40% geral) com escanteios concedidos pelo adversário no mesmo
  contexto.
- Pondere forma recente: temporada/contexto 40%, últimos 10 jogos 35%,
  últimos 5 jogos 25%.
- Head-to-head tem peso baixo (máximo 5%), nunca deixe H2H antigo dominar.
- Estime probabilidades para as linhas de Over/Under mais próximas do
  Expected Total, sem forçar todas as linhas.
- Se tiver odd, calcule EV = (probabilidade × odd) - 1. Só aponte uma
  recomendação quando houver EDGE real (diferença relevante entre sua
  probabilidade e a implícita na odd).
- Se a amostra for insuficiente ou os dados conflitantes, responda
  "SEM EDGE CLARO" — não force uma indicação.
- Nunca use "certeza" ou "garantido". Seja honesto sobre incerteza.
- Pesquise na web dados atualizados antes de responder.
- Responda em texto direto, pronto pra mensagem de Telegram, sem tabelas
  pesadas."""

PROMPT_GERAL = """Você é um analista esportivo cuidadoso, especialista em futebol e apostas
esportivas. Pesquise na web dados atualizados antes de responder. Seja honesto
sobre incerteza, nunca invente estatística, e nunca use "certeza" ou
"garantido". Responda em texto direto, pronto pra mensagem de Telegram."""


def get_updates():
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    resp = requests.get(url, params={"timeout": 0}, timeout=30)
    resp.raise_for_status()
    return resp.json().get("result", [])


def clear_updates(last_update_id):
    """Confirma pro Telegram que já processamos até esse update_id,
    pra não receber a mesma mensagem de novo na próxima checagem."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    requests.get(url, params={"offset": last_update_id + 1, "timeout": 0}, timeout=30)


def eh_sobre_escanteios(texto):
    palavras = ["escanteio", "corner", "córner"]
    return any(p in texto.lower() for p in palavras)


def ask_gemini(pergunta_usuario, contexto_sistema):
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    prompt_completo = f"{contexto_sistema}\n\nPergunta do usuário: {pergunta_usuario}"

    def chamar(usar_busca):
        body = {"contents": [{"parts": [{"text": prompt_completo}]}]}
        if usar_busca:
            body["tools"] = [{"google_search": {}}]
        resp = requests.post(url, json=body, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        candidatos = data.get("candidates", [])
        if not candidatos:
            return None
        partes = candidatos[0]["content"]["parts"]
        return "\n".join(p.get("text", "") for p in partes if "text" in p).strip()

    try:
        resultado = chamar(usar_busca=True)
        if resultado:
            return resultado
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code != 429:
            raise

    aviso = "⚠️ Busca na web indisponível agora, respondendo com conhecimento geral.\n\n"
    resultado = chamar(usar_busca=False)
    return aviso + (resultado or "Não consegui responder agora, tenta de novo.")


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    text = text[:4000] if text else "Não consegui gerar uma resposta."
    resp = requests.post(
        url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=30
    )
    resp.raise_for_status()


def main():
    updates = get_updates()
    if not updates:
        return

    last_update_id = max(u["update_id"] for u in updates)

    for update in updates:
        message = update.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        texto = message.get("text", "")

        # Só responde mensagens vindas do seu próprio chat
        if not texto or chat_id != str(TELEGRAM_CHAT_ID):
            continue

        contexto = METODOLOGIA_ESCANTEIOS if eh_sobre_escanteios(texto) else PROMPT_GERAL
        resposta = ask_gemini(texto, contexto)
        send_telegram(resposta)

    clear_updates(last_update_id)


if __name__ == "__main__":
    main()
