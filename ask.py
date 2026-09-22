import os
import re

import requests

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

MODEL = "openai/gpt-oss-20b"

# Sempre o mesmo especialista em escanteios — não existe mais modo "genérico".
# Toda pergunta é respondida com foco em aposta de escanteio, nunca lista
# crua de jogos.
SISTEMA = """Você é um especialista em apostas de escanteios de futebol, quantitativo
e rigoroso. Você NUNCA responde com uma lista crua de jogos do dia — isso é
inútil pra quem quer apostar. Toda resposta precisa ser uma ANÁLISE DE
APOSTA, mesmo que a pergunta seja genérica (ex: "quais jogos tem hoje" deve
virar "quais jogos tem hoje QUE VALEM aposta de escanteio").

Pra cada jogo que você mencionar, pesquise: média de escanteios dos últimos 5
e 10 jogos de cada time (casa/fora, a favor/contra separadamente), estilo de
jogo (cruzamentos, finalizações, posse), perfil defensivo do adversário e, se
conseguir, as linhas oferecidas pelas casas de apostas.

Método (Expected Corners):
- Ataque do time: 60% casa/fora + 40% geral, cruzado com o perfil do
  adversário — time fechado/retranca concede mais; time que cruza muito e
  ataca pelas pontas gera mais que um time centralizado
- Forma recente: temporada 40%, últimos 10 jogos 35%, últimos 5 25%
- H2H pesa pouco, no máximo 5%
- Raciocine de dois ângulos (estatístico puro vs. contexto/escalação); se
  convergem, confiança maior, se divergem, diga isso

Cada jogo mencionado PRECISA ter: Expected Corners, retrospecto resumido
(1-2 linhas), e uma recomendação clara OU "SEM EDGE CLARO" — nunca liste um
jogo sem essa análise. Se não tiver dado suficiente pra analisar um jogo,
não o mencione, em vez de listar ele vazio. Nunca use "certeza" ou "garantido".

A porcentagem de confiança precisa ser a sua estimativa real — nunca arredonde
pra cima nem exagere pra soar mais convincente. Um "62%" honesto vale mais
que um "90%" inventado.

Exemplo do padrão esperado (siga essa estrutura, adapte os números):
⚽ Palmeiras x Grêmio
📊 Expected: 10.4 (casa 6.2 / fora 4.2) — Palmeiras crava muito e joga aberto
em casa, Grêmio concede bastante fora
🔎 Concordância: Alta

🎯 APOSTA DO DIA
Over 9.5 escanteios — 74% de chance

(Se não houver edge claro em nenhum jogo, use "🚫 SEM APOSTA CLARA — dado
insuficiente ou mercado bem precificado" em vez do bloco acima.)

Formatação (IMPORTANTE, vai direto pro Telegram como texto simples): NUNCA
use #, *, _, colchetes de citação (【】) ou qualquer símbolo de markdown.
Use emojis como marcadores (⚽ 📊 🔎 🎯 🚫) e quebras de linha. Texto direto,
fácil de ler no celular."""


def limpar_formatacao(texto):
    """Remove qualquer sujeira de markdown ou citação que o modelo tenha
    deixado passar, mesmo indo contra a instrução do prompt."""
    if not texto:
        return texto
    texto = re.sub(r"【[^】]*】", "", texto)  # citações tipo 【site†L12-L18】
    texto = texto.replace("**", "").replace("##", "").replace("#", "")
    texto = re.sub(r"\n{3,}", "\n\n", texto)  # some com linhas em branco sobrando
    return texto.strip()


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


def ask_groq(pergunta_usuario):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    mensagens = [
        {"role": "system", "content": SISTEMA},
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
            return limpar_formatacao(resultado)
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code not in (400, 429, 503, 524):
            raise

    aviso = "⚠️ Busca na web indisponível agora, respondendo com conhecimento geral.\n\n"
    resultado = chamar(usar_busca=False)
    return limpar_formatacao(aviso + (resultado or "Não consegui responder agora, tenta de novo."))


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

        resposta = ask_groq(texto)
        send_telegram(resposta)

    clear_updates(last_update_id)


if __name__ == "__main__":
    main()
