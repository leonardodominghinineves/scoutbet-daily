// ScoutBet — "campainha" do Telegram (Cloudflare Worker, plano grátis).
// Recebe sua mensagem na hora, responde "analisando..." e dispara o workflow
// "Responder no Telegram" no GitHub, que manda a análise em ~1 minuto.
//
// Variáveis (Settings → Variables and Secrets do Worker):
//   TELEGRAM_TOKEN    token do bot
//   TELEGRAM_CHAT_ID  seu chat_id (só você usa o bot)
//   GH_TOKEN          token do GitHub (fine-grained, só esse repo, Contents: Read and write)
//   GH_REPO           ex: leonardo/scoutbet-daily
//   WEBHOOK_SECRET    uma senha qualquer que você inventa (só letras e números)
//
// Depois de publicar, abra no navegador UMA vez:
//   https://SEU-WORKER.workers.dev/setup?key=WEBHOOK_SECRET

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);

    if (req.method === "GET" && url.pathname === "/setup") {
      if (url.searchParams.get("key") !== env.WEBHOOK_SECRET) return new Response("chave errada", { status: 403 });
      const r = await tg(env, "setWebhook", {
        url: `${url.origin}/webhook`,
        secret_token: env.WEBHOOK_SECRET,
        allowed_updates: ["message"],
        drop_pending_updates: true,
      });
      return new Response(JSON.stringify(await r.json(), null, 2), { headers: { "content-type": "application/json" } });
    }

    if (req.method !== "POST" || url.pathname !== "/webhook") return new Response("ScoutBet ok");
    if (req.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }

    const upd = await req.json().catch(() => ({}));
    const msg = upd.message;
    if (!msg || !msg.text || String(msg.chat.id) !== String(env.TELEGRAM_CHAT_ID)) return new Response("ok");

    ctx.waitUntil(processar(env, msg));
    return new Response("ok"); // responde rápido pro Telegram não reenviar
  },
};

async function processar(env, msg) {
  const chat_id = msg.chat.id;
  const texto = msg.text.slice(0, 500);
  const rapido = /^\/(ajuda|start|help|historico)/i.test(texto);

  const dispatch = fetch(`https://api.github.com/repos/${env.GH_REPO}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "scoutbet-worker",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ event_type: "telegram", client_payload: { text: texto, chat_id } }),
  });

  const avisos = [tg(env, "sendChatAction", { chat_id, action: "typing" })];
  if (!rapido) avisos.push(tg(env, "sendMessage", { chat_id, text: "⏳ Analisando os números... (~1 min)" }));

  const [r] = await Promise.all([dispatch, ...avisos]);
  if (r.status !== 204) {
    const erro = (await r.text()).slice(0, 200);
    await tg(env, "sendMessage", { chat_id, text: `⚠️ Não consegui acionar o GitHub (${r.status}). Confira GH_TOKEN e GH_REPO.\n${erro}` });
  }
}

function tg(env, metodo, corpo) {
  return fetch(`https://api.telegram.org/bot${env.TELEGRAM_TOKEN}/${metodo}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(corpo),
  });
}
