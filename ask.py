import os

import requests

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

MODEL = "openai/gpt-oss-20b"

# Metodologia completa de escanteios (usada quando a pergunta é sobre esse mercado)
METODOLOGIA_ESCANTEIOS = """Você é um analista especialista em escanteios de futebol, quantitativo
e conservador. Expected Corners = ataque da equipe (peso maior casa/fora:
60/40) + escanteios concedidos pelo adversário no mesmo contexto. Forma
recente: temporada 40%, últimos 10 jogos 35%, últimos 5 25%. H2H pesa pouco
(máx 5%). Estime só as linhas Over/Under próximas do Expected Total. Se tiver
odd, calcule EV. Só recomende com EDGE real; senão, "SEM EDGE CLARO" — não
force. Nunca use "certeza" ou "garantido". Pesquise na web dados atualizados
antes de responder. Responda em texto direto, pronto pra Telegram."""

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


def ask_groq(pergunta_usuario, contexto_sistema):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    mensagens = [
        {"role": "system", "content": contexto_sistema},
        {"role": "user", "content": pergunta_usuario},
    ]

    def chamar(usar_busca):
        body = {"model": MODEL, "messages": mensagens, "max_completion_tokens": 2048}
        if usar_busca:
            body["tool_choice"] = "required"
            body["tools"] = [{"type": "browser_search"}]
        resp = requests.post(url, headers=headers, json=body, timeout=120)
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
            return resultado
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code not in (429, 503, 524):
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
        resposta = ask_groq(texto, contexto)
        send_telegram(resposta)

    clear_updates(last_update_id)


if __name__ == "__main__":
    main()
