"""Telegram, IA (Groq/Grok, compatível OpenAI), análise dos jogos e histórico de acertos."""
import html
import json
import os
import re
from datetime import datetime, timedelta

import requests

import dados
from modelo import Modelo, melhor_dica

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# IA: por padrão Groq (grátis). Pra usar o Grok da xAI, configure
# LLM_BASE_URL=https://api.x.ai/v1 e LLM_MODEL=grok-... nos secrets/variables.
LLM_API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL") or "https://api.groq.com/openai/v1"
LLM_MODEL = os.environ.get("LLM_MODEL") or "llama-3.3-70b-versatile"

ARQ_DICAS = os.path.join(os.path.dirname(__file__), "data", "dicas.json")
DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


# ---------------------------------------------------------------- Telegram

ENVIADAS = []  # o que o bot mandou nesta execução (vai pra memória da conversa)


def enviar(texto, chat_id=None):
    chat_id = chat_id or TELEGRAM_CHAT_ID
    ENVIADAS.append(texto)
    partes, atual = [], ""
    for bloco in texto.split("\n\n"):
        if len(atual) + len(bloco) + 2 > 3900:
            partes.append(atual); atual = ""
        atual += ("\n\n" if atual else "") + bloco
    partes.append(atual)
    for parte in partes:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                          json={"chat_id": chat_id, "text": parte, "parse_mode": "HTML",
                                "disable_web_page_preview": True}, timeout=30)
        if not r.ok:  # se o HTML der problema, manda como texto puro
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                          json={"chat_id": chat_id, "text": re.sub(r"<[^>]+>", "", parte)}, timeout=30)


def esc(t):
    return html.escape(str(t), quote=False)


# ---------------------------------------------------------------- IA

def perguntar_ia(sistema, usuario, max_tokens=350, historico=None):
    """Chamada curta à IA. Retorna None se não tiver chave ou falhar (o bot funciona sem).
    historico: lista de {"r": "user"|"bot", "t": texto} com a conversa recente."""
    if not LLM_API_KEY:
        return None
    try:
        r = requests.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={"model": LLM_MODEL, "temperature": 0.3, "max_tokens": max_tokens,
                  "messages": [{"role": "system", "content": sistema}]
                              + [{"role": "user" if h.get("r") == "user" else "assistant",
                                  "content": str(h.get("t", ""))[:400]} for h in (historico or [])[-8:]]
                              + [{"role": "user", "content": usuario}]},
            timeout=60)
        if not r.ok:
            print(f"IA respondeu {r.status_code}: {r.text[:300]}")
            return None
        txt = r.json()["choices"][0]["message"]["content"] or ""
        txt = re.sub(r"【[^】]*】", "", txt).replace("**", "").replace("#", "")
        return txt.strip() or None
    except Exception as e:  # noqa: BLE001
        print(f"IA falhou: {e}")
        return None


# ---------------------------------------------------------------- análise

def preparar(log=print):
    """Sincroniza o cache e monta o modelo."""
    cache = dados.carregar_cache()
    dados.sincronizar(cache, log=log)
    dados.salvar_cache(cache)
    partidas = dados.partidas_validas(cache)
    log(f"  partidas com escanteios: {len(partidas)}")
    return cache, Modelo(partidas)


def analisar(jogos, modelo):
    out = []
    for j in jogos:
        prev = modelo.prever(j["casa"]["id"], j["fora"]["id"], j["liga"])
        out.append({"jogo": j, "prev": prev, "dica": melhor_dica(prev)})
    return out


def rotulo_jogo(j):
    return f"{j['casa']['nome']} x {j['fora']['nome']}"


def nome_dica(a):
    d, j = a["dica"], a["jogo"]
    if d["tipo"] == "casa":
        return f"{j['casa']['nome']} {d['nome']} escanteios"
    if d["tipo"] == "fora":
        return f"{j['fora']['nome']} {d['nome']} escanteios"
    if d["tipo"] == "1x2":
        quem = j["casa"]["nome"] if d["lado"] == "casa" else j["fora"]["nome"]
        return f"{quem} com mais escanteios"
    return d["nome"]


def motivo(a):
    """Explicação curta e determinística (sem IA) do porquê."""
    p, j = a["prev"], a["jogo"]
    partes = []

    def f(x):
        return f"{x:.2f}".rstrip("0").rstrip(".") + "×"
    if abs(p["atq_casa"] - 1) >= 0.12:
        partes.append(f"{j['casa']['curto'] or j['casa']['nome']} gera {f(p['atq_casa'])} a média")
    if abs(p["def_fora"] - 1) >= 0.12:
        partes.append(f"{j['fora']['curto'] or j['fora']['nome']} cede {f(p['def_fora'])}")
    if abs(p["atq_fora"] - 1) >= 0.12:
        partes.append(f"{j['fora']['curto'] or j['fora']['nome']} gera {f(p['atq_fora'])}")
    if abs(p["def_casa"] - 1) >= 0.12:
        partes.append(f"{j['casa']['curto'] or j['casa']['nome']} cede {f(p['def_casa'])}")
    return "; ".join(partes[:3]) or "times perto da média da liga"


def cartao(a, i=None, comentario=None):
    j, p, d = a["jogo"], a["prev"], a["dica"]
    liga = dados.LIGAS.get(j["liga"], j["liga"])
    cab = f"{i}) " if i else "⚽ "
    linhas = [f"{cab}<b>{esc(rotulo_jogo(j))}</b> · {esc(liga)} · {j['inicio']:%H:%M}"]
    if d:
        linhas.append(f"🎯 <b>{esc(nome_dica(a))}</b> — {d['p']*100:.0f}%")
        linhas.append(f"💰 odd justa {d['justa']:.2f} · só entra se pagar ≥ <b>{d['minima']:.2f}</b>")
    linhas.append(f"📊 Esperado {p['total']:.1f} ({p['lh']:.1f} x {p['la']:.1f}) · média da liga {p['media_liga']:.1f}")
    linhas.append(f"🔎 {esc(motivo(a))}")
    if d:
        emoji = "✅" if d["conc"] == "Alta" else "🟡"
        linhas.append(f"{emoji} Forma recente: {d['conc'].lower()} (últimos 5 → {p['recente']:.1f})")
    if comentario:
        linhas.append(f"💬 {esc(comentario)}")
    return "\n".join(linhas)


def dados_para_ia(a):
    """Resumo compacto (poucos tokens) de um jogo pra IA comentar."""
    j, p, d = a["jogo"], a["prev"], a["dica"]
    s = (f"{rotulo_jogo(j)} ({dados.LIGAS.get(j['liga'])}). Esperado {p['total']:.1f} "
         f"(casa {p['lh']:.1f}, fora {p['la']:.1f}); média liga {p['media_liga']:.1f}; "
         f"forma últimos 5 = {p['recente']:.1f}. Índices (1.0 = média): ataque casa {p['atq_casa']:.2f}, "
         f"defesa casa {p['def_casa']:.2f}, ataque fora {p['atq_fora']:.2f}, defesa fora {p['def_fora']:.2f}. "
         f"Amostra: {p['n_casa']} e {p['n_fora']} jogos.")
    if d:
        s += f" Dica do modelo: {nome_dica(a)} {d['p']*100:.0f}% (odd mínima {d['minima']:.2f}, concordância {d['conc']})."
    return s


# ---------------------------------------------------------------- relatório

def relatorio(analises, dia, modelo, com_ia=True, top_n=3):
    ligas = {a["jogo"]["liga"] for a in analises}
    cab = (f"⚽ <b>ScoutBet · {DIAS_SEMANA[dia.weekday()]} {dia:%d/%m}</b>\n"
           f"{len(analises)} jogos analisados em {len(ligas)} ligas")
    com_dica = sorted([a for a in analises if a["dica"]], key=lambda a: -a["dica"]["score"])
    top = com_dica[:top_n]

    comentarios = {}
    if com_ia and top:
        sistema = ("Você é analista de apostas em escanteios. Para cada jogo, escreva UMA frase curta "
                   "(máx 20 palavras) explicando o porquê da dica em linguagem de apostador, usando só os "
                   "números fornecidos. Não invente escalação, lesão nem estatística. Sem markdown. "
                   "Responda no formato: 1) frase\n2) frase ...")
        txt = perguntar_ia(sistema, "\n".join(f"{i}) {dados_para_ia(a)}" for i, a in enumerate(top, 1)),
                           max_tokens=60 * len(top))
        for m in re.finditer(r"^\s*(\d)\)\s*(.+)$", txt or "", re.M):
            comentarios[int(m.group(1))] = m.group(2).strip()

    blocos = [cab]
    if top:
        blocos.append("🏆 <b>TOP DO DIA</b>")
        blocos += [cartao(a, i, comentarios.get(i)) for i, a in enumerate(top, 1)]
    else:
        blocos.append("🚫 Nenhuma aposta com vantagem clara hoje. Melhor passar do que forçar.")

    outros = [a for a in analises if a not in top][:14]
    if outros:
        linhas = ["📋 <b>Outros jogos</b> (esperado · leitura)"]
        for a in outros:
            j, p, d = a["jogo"], a["prev"], a["dica"]
            if d:
                leitura = f"{esc(nome_dica(a))} {d['p']*100:.0f}% (≥{d['minima']:.2f})"
            elif min(p["n_casa"], p["n_fora"]) < 6:
                leitura = "poucos dados"
            else:
                leitura = "sem vantagem"
            linhas.append(f"• {j['inicio']:%H:%M} {esc(rotulo_jogo(j))} — {p['total']:.1f} · {leitura}")
        blocos.append("\n".join(linhas))

    hist = resumo_historico()
    if hist:
        blocos.append(hist)
    blocos.append("ℹ️ Odd justa = 1 ÷ probabilidade. Só tem valor se a casa pagar acima da odd mínima. "
                  "Escanteio varia muito: aposte pouco e com disciplina.")
    return "\n\n".join(blocos), top


# ---------------------------------------------------------------- histórico de dicas

def carregar_dicas():
    try:
        with open(ARQ_DICAS, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def salvar_dicas(lst):
    os.makedirs(os.path.dirname(ARQ_DICAS), exist_ok=True)
    with open(ARQ_DICAS, "w", encoding="utf-8") as f:
        json.dump(lst, f, ensure_ascii=False, indent=0)


def registrar_dicas(top, dia):
    lst = carregar_dicas()
    ids = {x["evento"] for x in lst}
    for a in top:
        j, d = a["jogo"], a["dica"]
        if j["id"] in ids:
            continue
        lst.append({"dia": dia.isoformat(), "evento": j["id"], "jogo": rotulo_jogo(j),
                    "tipo": d["tipo"], "lado": d["lado"], "linha": d["linha"],
                    "p": round(d["p"], 3), "minima": round(d["minima"], 2), "resultado": None})
    salvar_dicas(lst)


def conferir_dicas(cache):
    """Marca green/red nas dicas cujo jogo já terminou."""
    lst = carregar_dicas()
    partidas = cache.get("partidas", {})
    for x in lst:
        if x["resultado"] is not None:
            continue
        p = partidas.get(x["evento"])
        if not p or p.get("hc") is None or p.get("ac") is None:
            continue
        hc, ac = p["hc"], p["ac"]
        if x["tipo"] == "1x2":
            ok = hc > ac if x["lado"] == "casa" else ac > hc
        else:
            valor = {"total": hc + ac, "casa": hc, "fora": ac}[x["tipo"]]
            ok = valor > x["linha"] if x["lado"] == "over" else valor < x["linha"]
        x["resultado"] = "green" if ok else "red"
        x["placar_esc"] = f"{int(hc)}-{int(ac)}"
    salvar_dicas(lst)
    return lst


def resumo_historico(dias=30):
    lst = carregar_dicas()
    corte = (datetime.now(dados.BRT).date() - timedelta(days=dias)).isoformat()
    feitos = [x for x in lst if x["resultado"] and x["dia"] >= corte]
    if not feitos:
        return None
    g = sum(x["resultado"] == "green" for x in feitos)
    esperado = sum(x["p"] for x in feitos) / len(feitos)
    return (f"📈 Histórico {dias}d: <b>{g}/{len(feitos)}</b> greens ({g/len(feitos)*100:.0f}%) · "
            f"o modelo previa {esperado*100:.0f}%")
