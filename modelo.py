"""Modelo de escanteios.

Ideia central (é o que as casas também fazem, de forma mais simples):
  escanteios esperados do mandante  = média da liga (casa) × força ofensiva do mandante × quanto o visitante cede
  escanteios esperados do visitante = média da liga (fora) × força ofensiva do visitante × quanto o mandante cede

- As forças são calculadas jogo a jogo, sempre comparando com a média da liga
  daquele jogo. Assim um time que joga Brasileirão e Libertadores tem tudo na
  mesma régua.
- Jogos recentes pesam mais (meia-vida de 10 jogos).
- Com poucos jogos, a força é puxada pra média (evita "time com 2 jogos = 14
  escanteios por jogo").
- A distribuição é Binomial Negativa: escanteio varia mais que uma Poisson, e a
  variância real de cada liga é medida nos dados.
- Resultado: probabilidade de cada linha e "odd justa" (1/prob). Só há valor se
  a casa pagar acima da odd justa.
"""
from collections import defaultdict
from math import exp, lgamma, log

MEIA_VIDA = 10       # jogos
PESO_PRIOR = 4.0     # "jogos imaginários" na média, pra estabilizar amostras pequenas
MIN_JOGOS = 6        # abaixo disso o jogo não recebe dica
MIN_JOGOS_LIGA = 30  # abaixo disso usa a média geral


class Modelo:
    def __init__(self, partidas):
        self.partidas = partidas
        self._base_ligas()
        self._forcas()

    # ---------------------------------------------------------- médias por liga
    def _base_ligas(self):
        acc = defaultdict(lambda: [0, 0.0, 0.0, 0.0])  # n, soma casa, soma fora, soma total²
        for p in self.partidas:
            for chave in (p["l"], "_geral"):
                a = acc[chave]
                t = p["hc"] + p["ac"]
                a[0] += 1; a[1] += p["hc"]; a[2] += p["ac"]; a[3] += t * t
        self.ligas = {}
        g = acc["_geral"]
        geral = self._resumo(g) if g[0] else {"n": 0, "casa": 5.3, "fora": 4.4, "disp": 1.2}
        self.ligas["_geral"] = geral
        for chave, a in acc.items():
            if chave != "_geral":
                self.ligas[chave] = self._resumo(a) if a[0] >= MIN_JOGOS_LIGA else dict(geral, n=a[0])

    @staticmethod
    def _resumo(a):
        n, sc, sf, sq = a
        casa, fora = sc / n, sf / n
        media = casa + fora
        var = sq / n - media ** 2
        disp = min(max(var / media if media else 1.2, 1.0), 1.6)
        return {"n": n, "casa": casa, "fora": fora, "disp": disp}

    def base(self, liga):
        return self.ligas.get(liga) or self.ligas["_geral"]

    # ---------------------------------------------------------- força dos times
    def _forcas(self):
        hist = defaultdict(list)  # time -> [(data, razão_ataque, razão_defesa, esc_pro, esc_contra, casa?)]
        for p in self.partidas:
            b = self.base(p["l"])
            hist[p["h"]].append((p["d"], p["hc"] / b["casa"], p["ac"] / b["fora"], p["hc"], p["ac"], True))
            hist[p["a"]].append((p["d"], p["ac"] / b["fora"], p["hc"] / b["casa"], p["ac"], p["hc"], False))
        self.nomes = {}
        for p in self.partidas:
            self.nomes[p["h"]] = p["hn"]; self.nomes[p["a"]] = p["an"]
        self.hist = {t: sorted(v, key=lambda x: x[0] or "") for t, v in hist.items()}

    def forca(self, time, ultimos=None, meia_vida=MEIA_VIDA, prior=PESO_PRIOR):
        jogos = self.hist.get(str(time), [])
        if ultimos:
            jogos = jogos[-ultimos:]
        sa = sd = sw = 0.0
        for k, j in enumerate(reversed(jogos)):
            w = 0.5 ** (k / meia_vida) if meia_vida else 1.0
            sa += w * j[1]; sd += w * j[2]; sw += w
        return {
            "ataque": (sa + prior) / (sw + prior),
            "defesa": (sd + prior) / (sw + prior),
            "n": len(self.hist.get(str(time), [])),
        }

    def perfil(self, time, n=10):
        """Médias simples (pra mostrar ao usuário)."""
        jogos = self.hist.get(str(time), [])[-n:]
        if not jogos:
            return None
        casa = [j for j in jogos if j[5]]
        fora = [j for j in jogos if not j[5]]
        m = lambda xs, i: round(sum(x[i] for x in xs) / len(xs), 1) if xs else None
        return {
            "jogos": len(jogos), "pro": m(jogos, 3), "contra": m(jogos, 4),
            "pro_casa": m(casa, 3), "pro_fora": m(fora, 3),
            "ult5": [int(j[3] + j[4]) for j in jogos[-5:]],
        }

    # ---------------------------------------------------------- previsão
    def prever(self, casa_id, fora_id, liga):
        b = self.base(liga)
        fc, ff = self.forca(casa_id), self.forca(fora_id)
        lh = b["casa"] * fc["ataque"] * ff["defesa"]
        la = b["fora"] * ff["ataque"] * fc["defesa"]

        # Mesma conta só com os últimos 5 jogos: serve pra ver se a forma recente confirma
        rc, rf = self.forca(casa_id, 5, 0, 2.0), self.forca(fora_id, 5, 0, 2.0)
        rec_h = b["casa"] * rc["ataque"] * rf["defesa"]
        rec_a = b["fora"] * rf["ataque"] * rc["defesa"]

        d = b["disp"]
        dist_h, dist_a = nb_pmf(lh, d), nb_pmf(la, d)
        dist_t = convolve(dist_h, dist_a)
        return {
            "lh": lh, "la": la, "total": lh + la,
            "recente": rec_h + rec_a, "rec_h": rec_h, "rec_a": rec_a,
            "n_casa": fc["n"], "n_fora": ff["n"],
            "atq_casa": fc["ataque"], "def_casa": fc["defesa"],
            "atq_fora": ff["ataque"], "def_fora": ff["defesa"],
            "media_liga": b["casa"] + b["fora"], "disp": d,
            "dist_h": dist_h, "dist_a": dist_a, "dist_t": dist_t,
        }


# ---------------------------------------------------------- matemática

def nb_pmf(media, disp, maximo=30):
    """Distribuição Binomial Negativa com variância = disp × média."""
    media = max(media, 0.05)
    if disp <= 1.001:
        pm = [exp(-media + k * log(media) - lgamma(k + 1)) for k in range(maximo + 1)]
    else:
        r = media / (disp - 1)
        p = 1 / disp
        pm = [exp(lgamma(k + r) - lgamma(r) - lgamma(k + 1) + r * log(p) + k * log(1 - p))
              for k in range(maximo + 1)]
    s = sum(pm)
    return [x / s for x in pm]


def convolve(a, b):
    out = [0.0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            out[i + j] += x * y
    return out


def p_over(dist, linha):
    return sum(p for k, p in enumerate(dist) if k > linha)


def p_mais_escanteios(dh, da):
    casa = fora = emp = 0.0
    for i, x in enumerate(dh):
        for j, y in enumerate(da):
            if i > j: casa += x * y
            elif i < j: fora += x * y
            else: emp += x * y
    return casa, emp, fora


# ---------------------------------------------------------- escolha das dicas

P_MIN, P_MAX = 0.58, 0.76   # odds ~1.30 a ~1.75: abaixo disso a casa paga pouco demais pra compensar
MARGEM = 1.06               # odd mínima = odd justa × 6% (margem de segurança)


def mercados(prev):
    """Todas as linhas avaliadas, com probabilidade."""
    lst = []
    for linha in (7.5, 8.5, 9.5, 10.5, 11.5, 12.5):
        po = p_over(prev["dist_t"], linha)
        lst.append(("total", f"Over {linha} escanteios", linha, "over", po, prev["total"], prev["recente"]))
        lst.append(("total", f"Under {linha} escanteios", linha, "under", 1 - po, prev["total"], prev["recente"]))
    for lado, dist, esp, rec in (("casa", prev["dist_h"], prev["lh"], prev["rec_h"]),
                                 ("fora", prev["dist_a"], prev["la"], prev["rec_a"])):
        for linha in (2.5, 3.5, 4.5, 5.5, 6.5):
            po = p_over(dist, linha)
            lst.append((lado, f"Over {linha}", linha, "over", po, esp, rec))
            lst.append((lado, f"Under {linha}", linha, "under", 1 - po, esp, rec))
    c, e, f = p_mais_escanteios(prev["dist_h"], prev["dist_a"])
    lst.append(("1x2", "Mandante com mais escanteios", None, "casa", c, prev["lh"] - prev["la"], prev["rec_h"] - prev["rec_a"]))
    lst.append(("1x2", "Visitante com mais escanteios", None, "fora", f, prev["la"] - prev["lh"], prev["rec_a"] - prev["rec_h"]))
    return lst


def concordancia(lado, linha, esperado, recente):
    """A forma recente (últimos 5) aponta pro mesmo lado da linha?"""
    if linha is None:  # mercado 1x2: esperado/recente são diferenças
        return "Alta" if recente > 0.5 else ("Média" if recente > -0.3 else "Baixa")
    if lado == "over":
        folga = recente - linha
    else:
        folga = linha - recente
    return "Alta" if folga >= 0.7 else ("Média" if folga >= -0.3 else "Baixa")


def melhor_dica(prev):
    """Escolhe a melhor aposta do jogo (ou None). Retorna dict com score pra ranquear."""
    if min(prev["n_casa"], prev["n_fora"]) < MIN_JOGOS:
        return None
    candidatos = []
    for tipo, nome, linha, lado, p, esp, rec in mercados(prev):
        if not (P_MIN <= p <= P_MAX):
            continue
        conc = concordancia(lado, linha, esp, rec)
        if conc == "Baixa":
            continue
        amostra = min(prev["n_casa"], prev["n_fora"])
        # score: probabilidade, bônus por concordância e amostra; preferência leve por odds melhores
        score = p + (0.04 if conc == "Alta" else 0) + min(amostra, 20) * 0.002
        if tipo in ("casa", "fora"):
            score -= 0.015  # mercado de time tem limite menor e mais margem da casa
        candidatos.append({
            "tipo": tipo, "nome": nome, "linha": linha, "lado": lado, "p": p,
            "justa": 1 / p, "minima": MARGEM / p, "conc": conc, "score": score,
        })
    if not candidatos:
        return None
    return max(candidatos, key=lambda c: c["score"])
