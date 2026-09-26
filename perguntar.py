"""Workflow de resposta: disparado na hora pelo Cloudflare Worker quando você manda mensagem.

Comandos (não gastam token de IA):
  /hoje       relatório de hoje
  /amanha     relatório de amanhã
  /historico  dicas passadas com green/red
  /backtest   testa o modelo nos jogos já disputados
  /ajuda      lista de comandos
Qualquer outro texto: procura o time/jogo citado e responde com os números + comentário da IA.
"""
import os
import re
import unicodedata
from datetime import datetime, timedelta

import comum
import dados
from modelo import Modelo, melhor_dica, p_over

AJUDA = ("🤖 <b>ScoutBet</b> — especialista em escanteios\n\n"
         "/hoje — melhores apostas de hoje\n"
         "/amanha — melhores apostas de amanhã\n"
         "/historico — minhas dicas passadas (green/red)\n"
         "/backtest — teste do modelo nos jogos já disputados\n\n"
         "Ou pergunte livre: <i>\"Flamengo x Palmeiras vale over?\"</i>, <i>\"como tá o Arsenal de escanteio?\"</i>")

APELIDOS = {
    "fla": "flamengo", "mengao": "flamengo", "verdao": "palmeiras", "timao": "corinthians",
    "galo": "atletico-mg", "peixe": "santos", "tricolor paulista": "sao paulo", "spfc": "sao paulo",
    "colorado": "internacional", "inter": "internacional", "fogao": "botafogo", "vasco": "vasco da gama",
    "raposa": "cruzeiro", "furacao": "athletico-pr", "city": "manchester city", "united": "manchester united",
    "barca": "barcelona", "real": "real madrid", "psg": "paris saint-germain", "bayern": "bayern munich",
    "spurs": "tottenham", "juve": "juventus",
}


def norm(t):
    t = unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9\- ]", " ", t)


def achar_times(texto, nomes):
    """Retorna ids dos times citados no texto (por nome, nome curto ou apelido)."""
    t = " " + norm(texto) + " "
    for ap, real in APELIDOS.items():
        t = t.replace(f" {ap} ", f" {real} ")
    achados = []
    for tid, nome in nomes.items():
        n = norm(nome).strip()
        variantes = {n, n.replace(" fc", "").replace("fc ", "").strip()}
        if any(len(v) >= 4 and f" {v} " in t for v in variantes):
            achados.append((t.find(n), tid))
    achados.sort()
    return [tid for _, tid in achados]


def historico_txt():
    lst = comum.carregar_dicas()[-15:]
    if not lst:
        return "Ainda não tenho dicas registradas. Elas começam a aparecer depois do primeiro relatório diário."
    linhas = ["📒 <b>Últimas dicas</b>"]
    for x in reversed(lst):
        ic = {"green": "✅", "red": "❌"}.get(x["resultado"], "⏳")
        extra = f" ({x.get('placar_esc')})" if x.get("placar_esc") else ""
        linhas.append(f"{ic} {x['dia'][8:10]}/{x['dia'][5:7]} {comum.esc(x['jogo'])} — "
                      f"{x['tipo']} {x['lado']} {x['linha'] or ''} {x['p']*100:.0f}%{extra}")
    r = comum.resumo_historico()
    return "\n".join(linhas) + ("\n\n" + r if r else "")


def backtest_txt(partidas):
    """Walk-forward: pra cada jogo, prevê usando só jogos ANTERIORES e compara com o real."""
    if len(partidas) < 300:
        return "Poucos jogos no histórico pra um backtest confiável ainda."
    teste = partidas[-500:]
    faixas = {}                 # faixa de probabilidade -> [acertos, total]
    dicas = [0, 0, 0.0]         # acertos, total, soma prob prevista
    erro_modelo = erro_liga = 0.0
    jogos = 0
    passo = 25
    base = len(partidas) - len(teste)
    for ini in range(0, len(teste), passo):
        m = Modelo(partidas[:base + ini])
        for p in partidas[base + ini:base + ini + passo]:
            prev = m.prever(p["h"], p["a"], p["l"])
            if min(prev["n_casa"], prev["n_fora"]) < 6:
                continue
            hc, ac = p["hc"], p["ac"]
            real = hc + ac
            jogos += 1
            erro_modelo += abs(prev["total"] - real)
            erro_liga += abs(prev["media_liga"] - real)
            for linha in (7.5, 8.5, 9.5, 10.5, 11.5, 12.5):
                po = p_over(prev["dist_t"], linha)
                for prob, ok in ((po, real > linha), (1 - po, real < linha)):
                    if prob >= 0.5:
                        fx = min(int(prob * 10) * 10, 90)
                        f = faixas.setdefault(fx, [0, 0]); f[0] += ok; f[1] += 1
            d = melhor_dica(prev)
            if d:
                if d["tipo"] == "1x2":
                    ok = hc > ac if d["lado"] == "casa" else ac > hc
                else:
                    v = {"total": real, "casa": hc, "fora": ac}[d["tipo"]]
                    ok = v > d["linha"] if d["lado"] == "over" else v < d["linha"]
                dicas[0] += ok; dicas[1] += 1; dicas[2] += d["p"]
    if not jogos:
        return "Poucos jogos com amostra suficiente pro backtest."
    linhas = [f"🧪 <b>Backtest</b> ({jogos} jogos, prevendo só com o passado)",
              f"Erro médio no total de escanteios: modelo {erro_modelo/jogos:.2f} × só média da liga {erro_liga/jogos:.2f}",
              "", "Calibração (prob. prevista → acerto real):"]
    for fx in sorted(faixas):
        a, t = faixas[fx]
        if t >= 15:
            linhas.append(f"• {fx}-{fx+10}%: {a}/{t} = {a/t*100:.0f}%")
    if dicas[1]:
        linhas.append(f"\n🎯 Dicas que o bot teria dado: {dicas[0]}/{dicas[1]} = {dicas[0]/dicas[1]*100:.0f}% "
                      f"(previa {dicas[2]/dicas[1]*100:.0f}%)")
    linhas.append("Se o acerto real fica perto do previsto, as probabilidades são honestas.")
    return "\n".join(linhas)


def resposta_livre(texto, modelo):
    hoje = datetime.now(dados.BRT).date()
    times = achar_times(texto, modelo.nomes)
    contexto, cartoes = [], []

    if times:
        jogos = dados.proximos_jogos(dias=7, hoje=hoje)
        alvo = [j for j in jogos if j["casa"]["id"] in times or j["fora"]["id"] in times]
        if len(times) >= 2:  # citou os dois times: prioriza o confronto
            alvo = [j for j in alvo if {j["casa"]["id"], j["fora"]["id"]} >= set(times[:2])] or alvo
        for a in comum.analisar(alvo[:2], modelo):
            cartoes.append(comum.cartao(a))
            contexto.append(f"Jogo {a['jogo']['inicio']:%d/%m %H:%M}: " + comum.dados_para_ia(a))
        for tid in times[:2]:
            pf = modelo.perfil(tid)
            if pf:
                contexto.append(
                    f"{modelo.nomes[tid]} últimos {pf['jogos']} jogos: {pf['pro']} escanteios a favor, "
                    f"{pf['contra']} contra; a favor em casa {pf['pro_casa']}, fora {pf['pro_fora']}; "
                    f"totais dos últimos 5: {pf['ult5']}.")
        if not alvo:
            contexto.append("Esse time não tem jogo nos próximos 7 dias nas ligas cobertas.")
    else:
        jogos = dados.proximos_jogos(dias=1, hoje=hoje)
        melhores = sorted([a for a in comum.analisar(jogos, modelo) if a["dica"]],
                          key=lambda a: -a["dica"]["score"])[:3]
        contexto += ["Melhor de hoje: " + comum.dados_para_ia(a) for a in melhores]
        if not melhores:
            contexto.append("Hoje o modelo não achou aposta com vantagem clara.")

    sistema = (f"Você é o ScoutBet, especialista em apostas de escanteios. Hoje é {hoje:%d/%m/%Y}. "
               "Responda em português, direto, no máximo 6 linhas, sem markdown. Use SOMENTE os dados "
               "fornecidos; se faltar dado, diga que não tem. Nunca invente estatística, escalação ou jogo. "
               "Probabilidades são do modelo; não aumente. Odd justa = 1/probabilidade; só há valor acima dela. "
               "Se a pergunta não for sobre futebol/apostas, responda curto e sugira /ajuda.")
    usuario = "DADOS:\n" + ("\n".join(contexto) or "nenhum") + f"\n\nPERGUNTA: {texto}"
    ia = comum.perguntar_ia(sistema, usuario, max_tokens=300)

    partes = cartoes[:]
    if ia:
        partes.append("💬 " + comum.esc(ia))
    elif not cartoes:
        partes.append("Não achei esse time nas ligas cobertas. Tenta o nome completo, ou manda /hoje.")
    return "\n\n".join(partes)


def main():
    texto = (os.environ.get("MENSAGEM") or "/hoje").strip()
    chat_id = os.environ.get("CHAT_ID") or comum.TELEGRAM_CHAT_ID
    print(f"Pergunta: {texto!r}")
    cmd = norm(texto.split()[0]).strip() if texto.startswith("/") else ""

    if cmd in ("start", "ajuda", "help"):
        return comum.enviar(AJUDA, chat_id)
    if cmd == "historico":
        return comum.enviar(historico_txt(), chat_id)

    cache, modelo = comum.preparar()
    hoje = datetime.now(dados.BRT).date()

    if cmd == "backtest":
        return comum.enviar(backtest_txt(dados.partidas_validas(cache)), chat_id)
    if cmd in ("hoje", "amanha"):
        dia = hoje if cmd == "hoje" else hoje + timedelta(days=1)
        jogos = [j for j in dados.proximos_jogos(dias=2, hoje=hoje) if j["inicio"].date() == dia]
        if not jogos:
            return comum.enviar(f"Sem jogos {'hoje' if cmd == 'hoje' else 'amanhã'} nas ligas cobertas.", chat_id)
        texto_rel, _ = comum.relatorio(comum.analisar(jogos, modelo), dia, modelo)
        return comum.enviar(texto_rel, chat_id)

    comum.enviar(resposta_livre(texto, modelo), chat_id)


if __name__ == "__main__":
    main()
