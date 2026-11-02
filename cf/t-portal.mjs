/**
 * t-portal · t.legaga.top → WorkBuddy sites 上的「A 股全景复盘站」动态应用
 *
 * 为什么要有这一层：
 *   sites 托管的域名是 astock-panorama-15588.app.workbuddy.host，且网关要求
 *   分享码（?sharecode=）才放行子路径，直接 CNAME 过来会因为缺码得到 403。
 *   所以用 Worker 做反代：每次回源自动补码，浏览器地址栏始终是 t.legaga.top。
 *
 * 设计要点（都是实测踩出来的，别随手改）：
 *   1) 站点页面零外链、零上游域名，导航全是根相对路径 → 只透传 path+query，无需改写 HTML。
 *   2) **必须整块读完再返回**。直接透传 resp.body 会被截断（实测首页 50178B 只送到 40572B，
 *      断在表格中间，浏览器看着像"页面没写完"）。
 *   3) Workers 的 fetch 会替我们解压，但常把 content-encoding / content-length 原样带出来，
 *      浏览器再解一次就乱码 → 两个头必须删，长度按实际 byteLength 重设。
 *   4) **压缩交给 CF**。Worker 自己 gzip 会撞上 CF 边缘缓存的转码 bug（缓存命中时
 *      返回"zstd 套 gzip"嵌套流，老浏览器直接乱码）；CF 对动态响应按 Accept-Encoding
 *      转码是正确的，让 它干。同时对客户端回 private 头，杜绝 CF 边缘缓存坏版本。
 *   5) 上游 Set-Cookie 的 __wb_rsc 无 Domain 属性，会自然落到 t.legaga.top；
 *      万一将来带上游 Domain，浏览器会拒收 → 统一剥掉 Domain 属性。
 *   6) redirect: manual + 改写 Location，避免把用户甩回上游域名（分享码就暴露了）。
 *   7) **缓存要一直热**：链路实测 MISS 能卡到 60 秒（回源只要 4 秒，卡在跨境传输），
 *      HIT 时 1 秒。TTL 10 分钟 + Cron 每 2 分钟从 CF 内部预热 7 个主页面；
 *      缓存用 Worker 自己的 caches.default，CF 边缘缓存必须关（private 头）——
 *      它的 Vary/转码实现有坑，会存出编码错乱的版本。
 *   8) 回源失败重试一次（沙箱第一次常超时，第二次基本就好）。
 *   9) /__health 自检、/__warm 手动预热，不走上游页面。
 */

const ORIGIN = "https://astock-panorama-15588.app.workbuddy.host";
const SHARECODE = "KIG7D3KIAY";
const PUBLIC_HOST = "t.legaga.top";
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         + "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";
const TTL = 600;             // 边缘缓存秒数（Cron 每 2 分钟刷新，用户几乎总命中）
const RETRY = 1;             // 回源失败重试次数
const WARM = ["/", "/rank", "/rank?t=hot", "/concept", "/drivers", "/attr", "/brief"];

const DROP_REQ = ["host", "cf-connecting-ip", "cf-ipcountry", "cf-ray", "cf-visitor",
                  "cf-worker", "x-forwarded-proto", "x-forwarded-for", "x-real-ip",
                  "cdn-loop", "connection"];

const DROP_RES = ["content-encoding", "content-length", "transfer-encoding",
                  "connection", "keep-alive", "alt-svc"];

function originUrl(pathWithQuery) {
  const t = new URL(pathWithQuery, ORIGIN);
  t.searchParams.set("sharecode", SHARECODE);   // 永远补码，用户看不见
  return t.toString();
}

function reqHeaders(src) {
  const h = new Headers(src || {});
  for (const k of DROP_REQ) h.delete(k);
  if (!h.get("user-agent")) h.set("user-agent", UA);
  h.set("accept-encoding", "identity");        // 上游别压缩，省一层解压口径差异
  return h;
}

/** 拉上游一次，整理成可直接下发的 {status, headers, body} */
async function grab(pathWithQuery) {
  const headers = reqHeaders();
  let resp, lastErr;
  for (let i = 0; i <= RETRY; i++) {
    try {
      resp = await fetch(originUrl(pathWithQuery), { headers, redirect: "manual" });
      if (resp.status >= 500) throw new Error("upstream " + resp.status);
      lastErr = null;
      break;
    } catch (e) {
      lastErr = e;
    }
  }
  if (!resp) throw lastErr || new Error("upstream unreachable");

  const buf = await resp.arrayBuffer();          // 整块读完（第 2 条）

  const out = new Headers(resp.headers);
  for (const k of DROP_RES) out.delete(k);

  const loc = out.get("location");               // 第 6 条
  if (loc && loc.includes(ORIGIN)) {
    out.set("location", loc.split(ORIGIN).join("https://" + PUBLIC_HOST));
  }

  // 压缩交给 CF：它按客户端 Accept-Encoding 自动转码（实测 gzip/zstd 都正确）。
  // 不要自己 gzip——CF 边缘缓存 + 自编码会撞出"zstd 套 gzip"的嵌套坏版本（老浏览器乱码）。
  const body = buf;
  if (body.byteLength) out.set("content-length", String(body.byteLength));

  const cookies = resp.headers.getAll ? resp.headers.getAll("set-cookie") : [];   // 第 5 条
  if (cookies.length) {
    out.delete("set-cookie");
    for (const c of cookies) out.append("set-cookie", c.replace(/;\s*Domain=[^;]*/gi, ""));
  }

  return { status: resp.status, headers: out, body };
}

/** 写一份干净副本进边缘缓存（不带 cookie，长缓存） */
function cacheCopy(packed) {
  const h = new Headers(packed.headers);
  h.delete("set-cookie");
  h.delete("vary");
  h.delete("x-request-id");
  h.delete("x-trace-id");
  h.delete("cache-control");
  h.set("cache-control", "public, max-age=" + TTL);
  return new Response(packed.body.slice(0), { status: 200, headers: h });
}

async function warmOne(pathWithQuery) {
  const key = new Request("https://" + PUBLIC_HOST + pathWithQuery, { method: "GET" });
  const packed = await grab(pathWithQuery);
  if (packed.status !== 200) throw new Error("warm " + pathWithQuery + " -> " + packed.status);
  await caches.default.put(key, cacheCopy(packed));
  return packed.body.byteLength;
}

async function health() {
  const t0 = Date.now();
  try {
    const r = await fetch(originUrl("/"), {
      headers: { "user-agent": UA, "accept-encoding": "identity" },
    });
    const txt = await r.text();
    const pick = (re) => (txt.match(re) || [])[1] || "";
    return new Response(JSON.stringify({
      ok: r.status === 200 && txt.length > 5000,
      via: PUBLIC_HOST,
      origin: ORIGIN,
      status: r.status,
      chars: txt.length,
      ms: Date.now() - t0,
      title: pick(/<title>([^<]*)<\/title>/),
      trade_date: pick(/<h1>([^<]*)<\/h1>/),
      as_of: pick(/数据时点 ([0-9: -]+)/),
      cache_ttl: TTL,
      warm_pages: WARM,
    }, null, 2), {
      headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
    });
  } catch (e) {
    return new Response(JSON.stringify({ ok: false, via: PUBLIC_HOST, error: String(e) }), {
      status: 502,
      headers: { "content-type": "application/json; charset=utf-8" },
    });
  }
}

async function warmAll() {
  const t0 = Date.now();
  const rows = {};
  await Promise.all(WARM.map(async (p) => {
    try {
      rows[p] = { ok: true, bytes: await warmOne(p) };
    } catch (e) {
      rows[p] = { ok: false, error: String(e) };
    }
  }));
  return new Response(JSON.stringify({
    ok: WARM.every((p) => rows[p] && rows[p].ok),
    ms: Date.now() - t0,
    pages: rows,
  }, null, 2), {
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

export default {
  async fetch(request, env, ctx) {
    const u = new URL(request.url);

    if (u.pathname === "/__health") return health();
    if (u.pathname === "/__warm") return warmAll();

    const cache = caches.default;
    const cacheKey = new Request(u.toString(), { method: "GET" });
    const cacheable = request.method === "GET" && !u.pathname.startsWith("/api/")
                      && !request.headers.get("x-nc");

    if (cacheable) {
      const hit = await cache.match(cacheKey);
      if (hit) {
        const h = new Headers(hit.headers);
        const ae = request.headers.get("accept-encoding") || "";
        if (h.get("content-encoding") === "gzip" && !/\bgzip\b/i.test(ae)) {
          // 客户端不收 gzip：解压后再给，别送二进制
          const dec = hit.body.pipeThrough(new DecompressionStream("gzip"));
          const buf = await new Response(dec).arrayBuffer();
          h.delete("content-encoding");
          h.delete("vary");
          h.set("content-length", String(buf.byteLength));
          h.set("x-t-portal-cache", "HIT-PLAIN");
          return new Response(buf, { status: hit.status, headers: h });
        }
        h.set("x-t-portal-cache", "HIT");
        return new Response(hit.body, { status: hit.status, headers: h });
      }
    }

    let packed;
    try {
      packed = await grab(u.pathname + u.search);
    } catch (e) {
      return new Response("上游暂不可达，请稍后重试。\n" + String(e), {
        status: 502,
        headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" },
      });
    }

    if (cacheable && packed.status === 200 &&
        (packed.headers.get("content-type") || "").includes("text/html")) {
      ctx.waitUntil(cache.put(cacheKey, cacheCopy(packed)));   // 内部缓存：public
      packed.headers.set("cache-control", "private, max-age=" + TTL);  // 对 CF：别缓存
      packed.headers.set("x-t-portal-cache", "MISS");
    }

    return new Response(packed.body, { status: packed.status, headers: packed.headers });
  },

  /** Cron：每 2 分钟从 CF 内部预热主页面，绕开大陆→LAX 的慢链路 */
  async scheduled(event, env, ctx) {
    ctx.waitUntil(Promise.all(WARM.map((p) => warmOne(p).catch(() => 0))));
  },
};
