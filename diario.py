"""Workflow diário: analisa os jogos de hoje e manda o relatório no Telegram."""
from datetime import datetime

import comum
import dados


def main():
    hoje = datetime.now(dados.BRT).date()
    print(f"ScoutBet diário — {hoje}")
    cache, modelo = comum.preparar()
    comum.conferir_dicas(cache)  # atualiza green/red das dicas anteriores

    jogos = dados.proximos_jogos(dias=1, hoje=hoje)
    print(f"  jogos hoje: {len(jogos)}")
    if not jogos:
        msg = f"⚽ <b>ScoutBet · {hoje:%d/%m}</b>\n\nSem jogos hoje nas ligas cobertas."
        hist = comum.resumo_historico()
        comum.enviar(msg + ("\n\n" + hist if hist else ""))
        return

    analises = comum.analisar(jogos, modelo)
    texto, top = comum.relatorio(analises, hoje, modelo)
    comum.enviar(texto)
    comum.registrar_dicas(top, hoje)
    print(texto)


if __name__ == "__main__":
    main()
