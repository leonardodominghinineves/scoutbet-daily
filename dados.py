"""Coleta de dados: jogos e escanteios reais via API pública da ESPN (grátis, sem chave).

Guarda um cache em data/partidas.json com todas as partidas finalizadas
(escanteios de cada lado). Partida finalizada não muda, então só baixamos
o que é novo — isso deixa cada execução rápida.
"""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
ARQ_PARTIDAS = os.path.join(os.path.dirname(__file__), "data", "partidas.json")
BRT = timezone(timedelta(hours=-3))

# Ligas cobertas, em ordem de prioridade (as primeiras aparecem antes na mensagem).
# Pra tirar uma liga, apague a linha. Pra adicionar, use o código da ESPN.
LIGAS = {
    "bra.1": "Brasileirão",
    "conmebol.libertadores": "Libertadores",
    "uefa.champions": "Champions League",
    "eng.1": "Premier League",
    "esp.1": "La Liga",
    "ita.1": "Serie A",
    "ger.1": "Bundesliga",
    "fra.1": "Ligue 1",
    "bra.copa_do_brazil": "Copa do Brasil",
    "conmebol.sudamericana": "Sul-Americana",
    "uefa.europa": "Europa League",
    "por.1": "Liga Portugal",
    "ned.1": "Eredivisie",
    "arg.1": "Argentina",
    "bra.2": "Série B",
    "eng.2": "Championship",
}

DIAS_HISTORICO = 240   # quanto pra trás buscar na primeira execução
MAX_RESUMOS = 120      # limite de chamadas extras por execução (partidas sem escanteio no placar)

_sessao = requests.Session()
_sessao.headers["User-Agent"] = "Mozilla/5.0 (scoutbet)"


def _get(url, params=None, tentativas=3):
    for i in range(tentativas):
        try:
            r = _sessao.get(url, params=params, timeout=25)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 404):
                return None
        except (requests.RequestException, ValueError):
            pass
        time.sleep(1.5 * (i + 1))
    return None


def _stat(stats, nome):
    for s in stats or []:
        if s.get("name") == nome:
            try:
                return float(str(s.get("displayValue", "")).replace("%", ""))
            except ValueError:
                return None
    return None


def _parse_evento(ev, slug):
    try:
        comp = ev["competitions"][0]
        times = {c["homeAway"]: c for c in comp["competitors"]}
        casa, fora = times["home"], times["away"]
    except (KeyError, IndexError):
        return None
    status = comp.get("status", ev.get("status", {})).get("type", {})

    def lado(c):
        t = c.get("team", {})
        st = c.get("statistics", [])
        return {
            "id": str(t.get("id")),
            "nome": t.get("displayName") or t.get("name") or "?",
            "curto": t.get("shortDisplayName") or t.get("abbreviation") or "",
            "gols": _num(c.get("score")),
            "esc": _stat(st, "wonCorners"),
            "chutes": _stat(st, "totalShots"),
            "posse": _stat(st, "possessionPct"),
        }

    return {
        "id": str(ev.get("id")),
        "liga": slug,
        "data": ev.get("date"),  # ISO em UTC
        "estado": status.get("state"),  # pre / in / post
        "encerrado": bool(status.get("completed")),
        "casa": lado(casa),
        "fora": lado(fora),
    }


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def buscar_periodo(slug, inicio, fim):
    """Todas as partidas de uma liga entre duas datas (objetos date)."""
    eventos, d = [], inicio
    while d <= fim:
        ate = min(d + timedelta(days=27), fim)
        dados = _get(f"{BASE}/{slug}/scoreboard",
                     {"dates": f"{d:%Y%m%d}-{ate:%Y%m%d}", "limit": 1000})
        for ev in (dados or {}).get("events", []):
            p = _parse_evento(ev, slug)
            if p:
                eventos.append(p)
        d = ate + timedelta(days=1)
    return eventos


def _escanteios_do_resumo(slug, event_id):
    dados = _get(f"{BASE}/{slug}/summary", {"event": event_id})
    if not dados:
        return None
    res = {}
    for t in dados.get("boxscore", {}).get("teams", []):
        tid = str(t.get("team", {}).get("id"))
        res[tid] = _stat(t.get("statistics"), "wonCorners")
    return res


# ---------------------------------------------------------------- cache

def carregar_cache():
    try:
        with open(ARQ_PARTIDAS, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"partidas": {}, "sincronizado": {}}


def salvar_cache(cache):
    os.makedirs(os.path.dirname(ARQ_PARTIDAS), exist_ok=True)
    with open(ARQ_PARTIDAS, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))


def sincronizar(cache, hoje=None, log=print):
    """Baixa as partidas finalizadas que ainda não estão no cache."""
    hoje = hoje or datetime.now(BRT).date()
    partidas = cache.setdefault("partidas", {})
    sinc = cache.setdefault("sincronizado", {})

    def trabalho(slug):
        ultimo = sinc.get(slug)
        inicio = (datetime.fromisoformat(ultimo).date() - timedelta(days=4)) if ultimo \
            else hoje - timedelta(days=DIAS_HISTORICO)
        return slug, buscar_periodo(slug, inicio, hoje)

    with ThreadPoolExecutor(max_workers=6) as ex:
        resultados = list(ex.map(trabalho, LIGAS))

    novas, sem_esc = 0, []
    for slug, eventos in resultados:
        ok = 0
        for p in eventos:
            if not p["encerrado"]:
                continue
            ok += 1
            antigo = partidas.get(p["id"])
            if antigo and (antigo.get("hc") is not None or antigo.get("sem_dado")):
                continue
            partidas[p["id"]] = _compacto(p)
            novas += 1
            if p["casa"]["esc"] is None or p["fora"]["esc"] is None:
                sem_esc.append(p)
        if eventos:
            sinc[slug] = hoje.isoformat()
        log(f"  {slug}: {ok} partidas finalizadas no período")

    # Partidas cujo placar não trouxe escanteio: busca no resumo (limitado).
    pendentes = [p for p in sem_esc if not partidas[p["id"]].get("sem_dado")][:MAX_RESUMOS]
    if pendentes:
        with ThreadPoolExecutor(max_workers=8) as ex:
            resumos = list(ex.map(lambda p: _escanteios_do_resumo(p["liga"], p["id"]), pendentes))
        for p, r in zip(pendentes, resumos):
            reg = partidas[p["id"]]
            hc = (r or {}).get(p["casa"]["id"])
            ac = (r or {}).get(p["fora"]["id"])
            if hc is not None and ac is not None:
                reg["hc"], reg["ac"] = hc, ac
            else:
                reg["sem_dado"] = True
    log(f"  novas partidas no cache: {novas} (resumos extras: {len(pendentes)})")
    return cache


def _compacto(p):
    """Formato enxuto pra guardar no cache."""
    return {
        "l": p["liga"], "d": p["data"],
        "h": p["casa"]["id"], "a": p["fora"]["id"],
        "hn": p["casa"]["nome"], "an": p["fora"]["nome"],
        "hc": p["casa"]["esc"], "ac": p["fora"]["esc"],
        "hg": p["casa"]["gols"], "ag": p["fora"]["gols"],
        "hs": p["casa"]["chutes"], "as": p["fora"]["chutes"],
    }


def partidas_validas(cache):
    """Lista de partidas com escanteios dos dois lados, da mais antiga pra mais nova."""
    lst = [dict(id=k, **v) for k, v in cache.get("partidas", {}).items()
           if v.get("hc") is not None and v.get("ac") is not None]
    lst.sort(key=lambda x: x["d"] or "")
    return lst


# ---------------------------------------------------------------- próximos jogos

def proximos_jogos(dias=1, hoje=None):
    """Jogos ainda não iniciados entre hoje e hoje+dias-1 (horário de Brasília)."""
    hoje = hoje or datetime.now(BRT).date()
    fim = hoje + timedelta(days=dias - 1)

    def trabalho(slug):
        # +1 dia porque a ESPN agrupa por horário dos EUA
        return buscar_periodo(slug, hoje, fim + timedelta(days=1))

    with ThreadPoolExecutor(max_workers=8) as ex:
        todos = [p for lst in ex.map(trabalho, LIGAS) for p in lst]

    vistos, jogos = set(), []
    for p in todos:
        if p["id"] in vistos or p["estado"] != "pre" or not p["data"]:
            continue
        inicio = datetime.fromisoformat(p["data"].replace("Z", "+00:00")).astimezone(BRT)
        if not (hoje <= inicio.date() <= fim):
            continue
        vistos.add(p["id"])
        p["inicio"] = inicio
        jogos.append(p)
    ordem = list(LIGAS)
    jogos.sort(key=lambda j: (j["inicio"].date(), ordem.index(j["liga"]), j["inicio"]))
    return jogos
