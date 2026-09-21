import os

import requests

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

MODEL = "openai/gpt-oss-20b"

FORMATACAO = """Formatação (IMPORTANTE, vai direto pro Telegram como texto simples): NUNCA
use #, **, _, tabelas (|) ou qualquer símbolo de markdown. Use emojis como
marcadores (⚽ 📊 ✅ ⚠️) e quebras de linha. Texto direto, fácil de ler no
celular, sem enrolação."""

METODOLOGIA_ESCANTEIOS = f"""Você é um especialista em escanteios de futebol, quantitativo e
rigoroso. Pesquise o retrospecto recente dos times: média de escanteios dos
últimos 5 e 10 jogos (casa/fora, a favor/contra separadamente), estilo de jogo
(cruzamentos, finalizações, posse), perfil defensivo do adversário e, se
conseguir, as linhas oferecidas pelas casas (total e por time).

Método (Expected Corners):
- Ataque do time: 60% casa/fora + 40% geral, cruzado com o perfil do
  adversário — time fechado/retranca concede mais; time que cruza muito e
  ataca pelas pontas gera mais que um time centralizado
- Forma recente: temporada 40%, últimos 10 jogos 35%, últimos 5 25%
- H2H pesa pouco, no máximo 5%

Raciocine de DOIS ângulos: (1) estatístico puro — médias e Expected Corners,
e (2) contexto — escalação, motivação, estilo tático do confronto. Se
convergem, confiança maior; se divergem, diga isso.

Produza: Expected Corners mandante/visitante/total, intervalo provável,
probabilidade das 3-4 linhas mais próximas do Expected Total, e nível de
concordância entre os ângulos (Alta/Média/Baixa). Só recomende com edge claro
E concordância Alta/Média. Na dúvida, "SEM EDGE CLARO". Nunca use "certeza"
ou "garantido".

{FORMATACAO}"""

PROMPT_GERAL = f"""Você é um especialista em futebol e apostas esportivas, com foco
particular em escanteios. Pesquise dados atualizados antes de responder. Seja
honesto sobre incerteza, nunca invente estatística.

{FORMATACAO}"""


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
            return resultado
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code not in (400, 429, 503, 524):
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
