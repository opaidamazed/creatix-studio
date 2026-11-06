// Cloudflare Worker: لوحة تحكم البوت + API
// Binding: KV namespace باسم CFG
// Secrets: CLIENT_ID, CLIENT_SECRET, BOT_TOKEN, BOT_API_SECRET
// Variable: FRONT = رابط موقع GitHub Pages (مثال: https://name.github.io/repo/)
const D = "https://discord.com/api/v10";
const json = (o, s = 200) => new Response(JSON.stringify(o), { status: s, headers: { "content-type": "application/json" } });
const rid = () => crypto.randomUUID().replace(/-/g, "");
const cookie = (req, n) => (req.headers.get("cookie") || "").split("; ").find(c => c.startsWith(n + "="))?.split("=")[1];
const S = (x, n) => String(x ?? "").slice(0, n);

function clean(b) {
  const w = b.welcome || {};
  return {
    welcome: {
      on: !!w.on, channel: S(w.channel, 25), title: S(w.title, 256), text: S(w.text, 2000),
      color: /^#[0-9a-f]{6}$/i.test(w.color) ? w.color : "#7c3aed",
      image: /^https:\/\//.test(w.image) ? S(w.image, 500) : "", footer: S(w.footer, 200),
    },
    autorole: S(b.autorole, 25),
    replies: (Array.isArray(b.replies) ? b.replies : []).slice(0, 50)
      .map(r => ({ k: S(r.k, 100).toLowerCase(), v: S(r.v, 1000) })).filter(r => r.k && r.v),
  };
}
const DEF = clean({ welcome: { on: true, title: "أهلاً بيك!", text: "أهلاً {member} في {server} 🎉\nأنت العضو رقم {count}" } });
const getCfg = async (env, id) => (await env.CFG.get("cfg:" + id, "json")) || DEF;
async function userGuilds(env, sid, at) {
  const key = "ug:" + sid, c = await env.CFG.get(key, "json");
  if (c && Date.now() - c.t < 300000) return c.d;
  const r = await fetch(D + "/users/@me/guilds", { headers: { authorization: "Bearer " + at } });
  if (r.status === 401) return 401;
  const d = await r.json().catch(() => null);
  if (!Array.isArray(d)) return c ? c.d : 503;
  const slim = d.map(g => ({ id: g.id, name: g.name, owner: g.owner, permissions: g.permissions }));
  await env.CFG.put(key, JSON.stringify({ t: Date.now(), d: slim }), { expirationTtl: 86400 });
  return slim;
}
async function botGuildIds(env) {
  const c = await env.CFG.get("bg", "json");
  if (c && Date.now() - c.t < 60000) return c.d;
  const d = await bot(env, "/users/@me/guilds");
  if (!Array.isArray(d)) return c ? c.d : null;
  const ids = d.map(g => g.id);
  await env.CFG.put("bg", JSON.stringify({ t: Date.now(), d: ids }), { expirationTtl: 3600 });
  return ids;
}
const bot = (env, path) => fetch(D + path, { headers: { authorization: "Bot " + env.BOT_TOKEN } }).then(r => r.json());

const H = {
  async fetch(req, env) {
    const u = new URL(req.url), p = u.pathname;
    try {
      if (p === "/") return Response.redirect(env.FRONT, 302);

      if (p === "/login") {
        const st = rid();
        const q = new URLSearchParams({ client_id: env.CLIENT_ID, response_type: "code", scope: "identify guilds", redirect_uri: u.origin + "/callback", state: st });
        return new Response(null, { status: 302, headers: { location: "https://discord.com/oauth2/authorize?" + q, "set-cookie": "st=" + st + "; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=600" } });
      }

      if (p === "/callback") {
        const st = cookie(req, "st");
        if (!st || st !== u.searchParams.get("state")) return new Response("bad state", { status: 400 });
        const t = await (await fetch(D + "/oauth2/token", { method: "POST", body: new URLSearchParams({ client_id: env.CLIENT_ID, client_secret: env.CLIENT_SECRET, grant_type: "authorization_code", code: u.searchParams.get("code") || "", redirect_uri: u.origin + "/callback" }) })).json();
        if (!t.access_token) return new Response("login failed", { status: 400 });
        const sid = rid();
        await env.CFG.put("sess:" + sid, JSON.stringify({ at: t.access_token }), { expirationTtl: 518400 });
        return new Response(null, { status: 302, headers: { location: env.FRONT + "#sid=" + sid } });
      }

      let m = p.match(/^\/bot\/config\/(\d+)$/);
      if (m) {
        if (req.headers.get("authorization") !== "Bearer " + env.BOT_API_SECRET) return json({ error: "no" }, 401);
        return json(await getCfg(env, m[1]));
      }

      if (p.startsWith("/api/")) {
        const sid = (req.headers.get("authorization") || "").slice(7);
        const s = sid && await env.CFG.get("sess:" + sid, "json");
        if (!s) return json({ error: "auth" }, 401);
        const ug = await userGuilds(env, sid, s.at);
        if (ug === 401) return json({ error: "auth" }, 401);
        if (ug === 503) return json({ error: "busy" }, 503);
        const bids = await botGuildIds(env);
        if (!bids) return json({ error: "bot" }, 503);
        const botIds = new Set(bids);
        if (p === "/api/diag") return json({ user: ug.length, bot: bids.length, shared: ug.filter(g => botIds.has(g.id)).length });
        const ok = ug.filter(g => (g.owner || (BigInt(g.permissions) & 0x28n)) && botIds.has(g.id));
        if (p === "/api/guilds") return json(ok.map(g => ({ id: g.id, name: g.name })));

        m = p.match(/^\/api\/guilds\/(\d+)\/(meta|config)$/);
        if (!m || !ok.some(g => g.id === m[1])) return json({ error: "forbidden" }, 403);
        const [, id, what] = m;
        if (what === "meta") {
          const [ch, ro] = await Promise.all([bot(env, "/guilds/" + id + "/channels"), bot(env, "/guilds/" + id + "/roles")]);
          return json({
            channels: ch.filter(c => c.type === 0 || c.type === 5).sort((a, b) => a.position - b.position).map(c => ({ id: c.id, name: c.name })),
            roles: ro.filter(r => !r.managed && r.name !== "@everyone").sort((a, b) => b.position - a.position).map(r => ({ id: r.id, name: r.name })),
          });
        }
        if (req.method === "PUT") {
          const raw = await req.text();
          if (raw.length > 30000) return json({ error: "big" }, 413);
          await env.CFG.put("cfg:" + id, JSON.stringify(clean(JSON.parse(raw))));
          return json({ ok: true });
        }
        return json(await getCfg(env, id));
      }
      return new Response("not found", { status: 404 });
    } catch (e) {
      return json({ error: "server" }, 500);
    }
  },
};


export default {
  async fetch(req, env) {
    const h = { "access-control-allow-origin": new URL(env.FRONT).origin, "access-control-allow-headers": "authorization,content-type", "access-control-allow-methods": "GET,PUT,OPTIONS" };
    if (req.method === "OPTIONS") return new Response(null, { headers: h });
    const r = await H.fetch(req, env);
    const n = new Response(r.body, r);
    for (const k in h) n.headers.set(k, h[k]);
    return n;
  },
};
