/**
 * Smart Shelf CS17IUH - Cloudflare Worker API (D1)
 *
 * Drop-in replacement for the Express/MongoDB backend on Render, whose free
 * tier sleeps and costs the shelf a 30-60s cold start on every restock scan.
 * Workers have no cold start and D1 lives at the edge.
 *
 * Response shapes intentionally mirror the Express API exactly - including the
 * `_id` alias next to `id` - so the Jetson (cloud_sync.py) and the React admin
 * keep working without changes.
 *
 * Bindings (wrangler.jsonc): DB (D1), JWT_SECRET (secret), IMAGES (R2, optional)
 */

export interface Env {
  DB: D1Database;
  JWT_SECRET: string;
  IMAGES?: R2Bucket;
}

/* ------------------------------------------------------------------ utils */

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { ...CORS, "Content-Type": "application/json; charset=utf-8" },
  });

const err = (status: number, error: string, message?: string) =>
  json({ error, message: message ?? error }, status);

/** Mongo used 24-char hex ObjectIds; keep the same shape for new rows. */
const oid = () =>
  Array.from(crypto.getRandomValues(new Uint8Array(12)))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");

const nowIso = () => new Date().toISOString();

/** Every row is returned with both `id` and `_id` for client compatibility. */
const withMongoId = <T extends { id?: string }>(row: T | null) =>
  row ? ({ ...row, _id: row.id } as T & { _id?: string }) : row;

const rows = <T extends { id?: string }>(list: T[]) => list.map((r) => withMongoId(r)!);

/* ------------------------------------------------------------------- auth */

const b64url = (buf: ArrayBuffer | Uint8Array) => {
  const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};

const hmacKey = (secret: string) =>
  crypto.subtle.importKey("raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);

/** HS256 JWT via WebCrypto - no dependency needed. */
async function signJwt(payload: Record<string, unknown>, secret: string, days = 7) {
  const header = { alg: "HS256", typ: "JWT" };
  const body = { ...payload, iat: Math.floor(Date.now() / 1000),
    exp: Math.floor(Date.now() / 1000) + days * 86400 };
  const enc = (o: unknown) => b64url(new TextEncoder().encode(JSON.stringify(o)));
  const data = `${enc(header)}.${enc(body)}`;
  const sig = await crypto.subtle.sign("HMAC", await hmacKey(secret),
    new TextEncoder().encode(data));
  return `${data}.${b64url(sig)}`;
}

/* --------------------------------------------------------------- handlers */

type Ctx = { env: Env; req: Request; params: Record<string, string>; url: URL };

const listAll = async (env: Env, sql: string, ...binds: unknown[]) => {
  const { results } = await env.DB.prepare(sql).bind(...binds).all();
  return results as any[];
};

/* products ---------------------------------------------------------------- */

const productsList = async ({ env }: Ctx) =>
  json(rows(await listAll(env, "SELECT * FROM products ORDER BY createdAt DESC")));

const productGet = async ({ env, params }: Ctx) => {
  const row = await env.DB.prepare("SELECT * FROM products WHERE id = ?")
    .bind(params.id).first();
  return row ? json(withMongoId(row as any)) : err(404, "Product not found");
};

const productCreate = async ({ env, req }: Ctx) => {
  const b = (await req.json()) as any;
  if (!b?.product_name) return err(400, "product_name is required");
  const id = oid();
  await env.DB.prepare(
    `INSERT INTO products (id, product_id, product_name, img_url, price, discount,
       stock, weight, max_quantity, threshold, createdAt, updatedAt)
     VALUES (?,?,?,?,?,?,?,?,?,?,?,?)`
  ).bind(id, b.product_id ?? id, b.product_name, b.img_url ?? "", b.price ?? 0,
    b.discount ?? 0, b.stock ?? 0, b.weight ?? 0, b.max_quantity ?? 1,
    b.threshold ?? 1, nowIso(), nowIso()).run();
  const row = await env.DB.prepare("SELECT * FROM products WHERE id = ?").bind(id).first();
  return json(withMongoId(row as any), 201);
};

const PRODUCT_FIELDS = ["product_id", "product_name", "img_url", "price", "discount",
  "stock", "weight", "max_quantity", "threshold"];

const productUpdate = async ({ env, req, params }: Ctx) => {
  const b = (await req.json()) as any;
  const sets: string[] = [], vals: unknown[] = [];
  for (const f of PRODUCT_FIELDS) if (f in b) { sets.push(`${f} = ?`); vals.push(b[f]); }
  if (!sets.length) return err(400, "No updatable fields supplied");
  sets.push("updatedAt = ?"); vals.push(nowIso(), params.id);
  const res = await env.DB.prepare(`UPDATE products SET ${sets.join(", ")} WHERE id = ?`)
    .bind(...vals).run();
  if (!res.meta.changes) return err(404, "Product not found");
  const row = await env.DB.prepare("SELECT * FROM products WHERE id = ?").bind(params.id).first();
  return json(withMongoId(row as any));
};

const productDelete = async ({ env, params }: Ctx) => {
  const res = await env.DB.prepare("DELETE FROM products WHERE id = ?").bind(params.id).run();
  return res.meta.changes
    ? json({ message: "Product deleted successfully" })
    : err(404, "Product not found");
};

/* users / auth ------------------------------------------------------------ */

const usersList = async ({ env }: Ctx) =>
  json(rows(await listAll(env,
    `SELECT id, username, rfid, email, fullName, phone, avatar, address,
            dateOfBirth, gender, role, isActive, lastLogin, emailVerified,
            createdAt, updatedAt
     FROM users ORDER BY createdAt DESC`)));

/**
 * Login. Existing passwords are bcrypt hashes from the Express app; bcrypt is
 * not available in Workers, so verification is delegated to bcryptjs (pure JS).
 */
const login = async ({ env, req }: Ctx) => {
  // Fail loudly on a missing secret: WebCrypto otherwise throws a cryptic
  // "HMAC key length (0)" from deep inside signJwt.
  if (!env.JWT_SECRET) {
    return err(500, "JWT_SECRET is not configured",
      "Set it with `wrangler secret put JWT_SECRET` (or .dev.vars locally).");
  }
  const { username, password } = (await req.json()) as any;
  if (!username || !password) return err(400, "username and password are required");
  const user = await env.DB.prepare("SELECT * FROM users WHERE username = ?")
    .bind(username).first<any>();
  if (!user) return err(404, "User not found");

  const bcrypt = await import("bcryptjs");
  const ok = await bcrypt.compare(password, user.password);
  if (!ok) return err(400, "Invalid credentials");

  await env.DB.prepare("UPDATE users SET lastLogin = ? WHERE id = ?")
    .bind(nowIso(), user.id).run();

  const token = await signJwt({ id: user.id, role: user.role }, env.JWT_SECRET);
  delete user.password;
  return json({ token, user: withMongoId(user) });
};

const register = async ({ env, req }: Ctx) => {
  const b = (await req.json()) as any;
  if (!b?.username || !b?.password) return err(400, "username and password are required");
  const dup = await env.DB.prepare("SELECT id FROM users WHERE username = ?")
    .bind(b.username).first();
  if (dup) return err(409, "Username already exists");

  const bcrypt = await import("bcryptjs");
  const hash = await bcrypt.hash(b.password, 10);
  const id = oid();
  await env.DB.prepare(
    `INSERT INTO users (id, username, rfid, email, password, fullName, phone,
       avatar, address, dateOfBirth, gender, role, isActive, createdAt, updatedAt)
     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`
  ).bind(id, b.username, b.rfid ?? null, b.email ?? null, hash, b.fullName ?? null,
    b.phone ?? null, b.avatar ?? "", b.address ?? null, b.dateOfBirth ?? null,
    b.gender ?? null, b.role ?? "employee", 1, nowIso(), nowIso()).run();
  const row = await env.DB.prepare(
    "SELECT id, username, rfid, email, fullName, role FROM users WHERE id = ?"
  ).bind(id).first();
  return json({ message: "User registered successfully", user: withMongoId(row as any) }, 201);
};

const userDelete = async ({ env, params }: Ctx) => {
  const res = await env.DB.prepare("DELETE FROM users WHERE id = ?").bind(params.id).run();
  return res.meta.changes ? json({ message: "User deleted" }) : err(404, "User not found");
};

/* shelves ----------------------------------------------------------------- */

/** Shelves carry their assigned users as an array, like the Mongo document. */
const shelfWithUsers = async (env: Env, shelf: any) => {
  const users = await listAll(env,
    `SELECT u.id, u.username, u.rfid, u.email, u.fullName, u.role
     FROM shelf_users su JOIN users u ON u.id = su.user_id WHERE su.shelf_id = ?`,
    shelf.id);
  return { ...withMongoId(shelf), user_id: rows(users) };
};

const shelvesList = async ({ env }: Ctx) => {
  const list = await listAll(env, "SELECT * FROM shelves ORDER BY createdAt DESC");
  return json(await Promise.all(list.map((s) => shelfWithUsers(env, s))));
};

const shelfGet = async ({ env, params }: Ctx) => {
  const s = await env.DB.prepare("SELECT * FROM shelves WHERE id = ?").bind(params.id).first();
  return s ? json(await shelfWithUsers(env, s)) : err(404, "Shelf not found");
};

/**
 * GET /api/shelves/get-products/:shelfId
 * The Jetson reads response.json()["products"], one entry per compartment in
 * floor/column order - empty slots included with null product fields.
 */
const shelfProducts = async ({ env, params }: Ctx) => {
  const shelf = await env.DB.prepare("SELECT * FROM shelves WHERE id = ?")
    .bind(params.shelfId).first<any>();
  if (!shelf) return err(404, "Shelf not found",
    `Shelf with ID ${params.shelfId} does not exist.`);

  const cells = await listAll(env,
    `SELECT lc.quantity, lc.floor, lc.column_index,
            p.id AS pid, p.product_name, p.price, p.discount,
            p.max_quantity, p.weight, p.img_url
     FROM loadcells lc LEFT JOIN products p ON p.id = lc.product_id
     WHERE lc.shelf_id = ? ORDER BY lc.floor, lc.column_index`,
    params.shelfId);

  const products = cells.map((c: any) => ({
    product_id: c.pid ?? null,
    product_name: c.product_name ?? null,
    price: c.price ?? null,
    discount: c.discount ?? null,
    max_quantity: c.max_quantity ?? null,
    weight: c.weight ?? null,
    img_url: c.img_url ?? null,
    quantity: c.quantity,
    floor: c.floor,
    column: c.column_index,
  }));

  return json({
    shelf: { shelf_id: shelf.shelf_id, _id: shelf.id },
    products,
    message: "Products retrieved successfully.",
  });
};

/**
 * GET /api/shelves/get-employee/:shelfId
 * The Jetson reads [u["rfid"] for u in response.json()["users"]].
 */
const shelfEmployees = async ({ env, params }: Ctx) => {
  const shelf = await env.DB.prepare("SELECT * FROM shelves WHERE id = ?")
    .bind(params.shelfId).first<any>();
  if (!shelf) return err(404, "Shelf not found");

  const users = await listAll(env,
    `SELECT u.id, u.username, u.rfid, u.email, u.fullName, u.phone, u.role, u.isActive
     FROM shelf_users su JOIN users u ON u.id = su.user_id WHERE su.shelf_id = ?`,
    params.shelfId);

  return json({
    shelf_id: shelf.shelf_id,
    users: rows(users),
    message: users.length ? "Users retrieved successfully." : "No users assigned yet.",
  });
};

const shelfQr = async ({ env, params }: Ctx) => {
  const s = await env.DB.prepare("SELECT shelf_id, qr FROM shelves WHERE id = ?")
    .bind(params.shelfId).first<any>();
  return s ? json({ shelf_id: s.shelf_id, qr: s.qr }) : err(404, "Shelf not found");
};

const shelfLoadcells = async ({ env, params }: Ctx) =>
  json(rows(await listAll(env,
    `SELECT lc.*, lc.column_index AS "column", p.product_name, p.img_url
     FROM loadcells lc LEFT JOIN products p ON p.id = lc.product_id
     WHERE lc.shelf_id = ? ORDER BY lc.floor, lc.column_index`, params.shelfId)));

/* loadcells --------------------------------------------------------------- */

const loadcellsList = async ({ env }: Ctx) =>
  json(rows(await listAll(env,
    `SELECT lc.*, lc.column_index AS "column" FROM loadcells lc
     ORDER BY lc.shelf_id, lc.floor, lc.column_index`)));

const loadcellUpdate = async ({ env, req, params }: Ctx) => {
  const b = (await req.json()) as any;
  const map: Record<string, string> = { column: "column_index" };
  const allowed = ["load_cell_name", "product_id", "previous_product_id",
    "floor", "column", "threshold", "quantity", "error"];
  const sets: string[] = [], vals: unknown[] = [];
  for (const f of allowed) if (f in b) { sets.push(`${map[f] ?? f} = ?`); vals.push(b[f]); }
  if (!sets.length) return err(400, "No updatable fields supplied");
  vals.push(params.id);
  const res = await env.DB.prepare(`UPDATE loadcells SET ${sets.join(", ")} WHERE id = ?`)
    .bind(...vals).run();
  return res.meta.changes ? json({ message: "Load cell updated" }) : err(404, "Load cell not found");
};

/* combos ------------------------------------------------------------------ */

/** The Jetson reads response.json()["data"] and each combo's products[]._id. */
const combosList = async ({ env }: Ctx) => {
  const list = await listAll(env, "SELECT * FROM combos ORDER BY createdAt DESC");
  const data = await Promise.all(list.map(async (c: any) => ({
    ...withMongoId(c),
    products: rows(await listAll(env,
      `SELECT p.id, p.product_name, p.price, p.img_url
       FROM combo_products cp JOIN products p ON p.id = cp.product_id
       WHERE cp.combo_id = ?`, c.id)),
  })));
  return json({ data, message: "Combos retrieved successfully." });
};

const comboCreate = async ({ env, req }: Ctx) => {
  const b = (await req.json()) as any;
  if (!b?.name) return err(400, "name is required");
  const id = oid();
  await env.DB.prepare(
    `INSERT INTO combos (id, name, description, image, price, oldPrice,
       validFrom, validTo, createdAt, updatedAt) VALUES (?,?,?,?,?,?,?,?,?,?)`
  ).bind(id, b.name, b.description ?? "", b.image ?? "", b.price ?? 0,
    b.oldPrice ?? 0, b.validFrom ?? null, b.validTo ?? null, nowIso(), nowIso()).run();
  const ids: string[] = b.products ?? [];
  if (ids.length) {
    await env.DB.batch(ids.map((pid) =>
      env.DB.prepare("INSERT OR IGNORE INTO combo_products (combo_id, product_id) VALUES (?,?)")
        .bind(id, pid)));
  }
  return json({ message: "Combo created", id, _id: id }, 201);
};

const comboDelete = async ({ env, params }: Ctx) => {
  const res = await env.DB.prepare("DELETE FROM combos WHERE id = ?").bind(params.id).run();
  return res.meta.changes ? json({ message: "Combo deleted" }) : err(404, "Combo not found");
};

/* posters ----------------------------------------------------------------- */

/** The Jetson reads response.json()["data"] and each poster's image_url. */
const postersList = async ({ env }: Ctx) =>
  json({ data: rows(await listAll(env, "SELECT * FROM posters ORDER BY createdAt DESC")) });

const posterCreate = async ({ env, req }: Ctx) => {
  const b = (await req.json()) as any;
  if (!b?.image_url) return err(400, "image_url is required");
  const id = oid();
  await env.DB.prepare(
    "INSERT INTO posters (id, image_url, createdAt, updatedAt) VALUES (?,?,?,?)"
  ).bind(id, b.image_url, nowIso(), nowIso()).run();
  return json({ id, _id: id, image_url: b.image_url }, 201);
};

const posterDelete = async ({ env, params }: Ctx) => {
  const res = await env.DB.prepare("DELETE FROM posters WHERE id = ?").bind(params.id).run();
  return res.meta.changes ? json({ message: "Poster deleted" }) : err(404, "Poster not found");
};

/* sepay config ------------------------------------------------------------ */

/**
 * The Jetson writes this response straight into database/sepay_info.json, so
 * the field names must stay exactly as the Express version returned them.
 */
const sepayForShelf = async ({ env, params }: Ctx) => {
  const row = await env.DB.prepare("SELECT * FROM sepay_configs WHERE shelf_id = ?")
    .bind(params.shelfId).first<any>();
  if (!row) return err(404, "Sepay config not found");
  return json(withMongoId(row));
};

const SEPAY_FIELDS = ["vietqrAccountNo", "vietqrAccountName", "vietqrAcqId",
  "sepayAuthToken", "sepayBankAccountId", "apiKey", "apiSecret", "merchantCode",
  "webhookUrl", "callbackUrl", "sandbox", "active"];

const sepayUpsert = async ({ env, req, params }: Ctx) => {
  const b = (await req.json()) as any;
  const existing = await env.DB.prepare("SELECT id FROM sepay_configs WHERE shelf_id = ?")
    .bind(params.shelfId).first<any>();

  if (existing) {
    const sets: string[] = [], vals: unknown[] = [];
    for (const f of SEPAY_FIELDS) if (f in b) { sets.push(`${f} = ?`); vals.push(b[f]); }
    if (!sets.length) return err(400, "No updatable fields supplied");
    sets.push("updatedAt = ?"); vals.push(nowIso(), existing.id);
    await env.DB.prepare(`UPDATE sepay_configs SET ${sets.join(", ")} WHERE id = ?`)
      .bind(...vals).run();
    const row = await env.DB.prepare("SELECT * FROM sepay_configs WHERE id = ?")
      .bind(existing.id).first();
    return json(withMongoId(row as any));
  }

  const id = oid();
  await env.DB.prepare(
    `INSERT INTO sepay_configs (id, shelf_id, vietqrAccountNo, vietqrAccountName,
       vietqrAcqId, sepayAuthToken, sepayBankAccountId, createdAt, updatedAt)
     VALUES (?,?,?,?,?,?,?,?,?)`
  ).bind(id, params.shelfId, b.vietqrAccountNo ?? "", b.vietqrAccountName ?? "",
    b.vietqrAcqId ?? "", b.sepayAuthToken ?? "", b.sepayBankAccountId ?? "",
    nowIso(), nowIso()).run();
  const row = await env.DB.prepare("SELECT * FROM sepay_configs WHERE id = ?").bind(id).first();
  return json(withMongoId(row as any), 201);
};

/* orders ------------------------------------------------------------------ */

/**
 * POST /api/orders
 * The Jetson posts multipart/form-data: the order fields plus a customer photo
 * and an `orderDetails` field holding a JSON string. The admin posts JSON.
 * The photo goes to R2 when the bucket is bound; without it the order is still
 * recorded (never lose a sale because an image could not be stored).
 */
const orderCreate = async ({ env, req }: Ctx) => {
  const type = req.headers.get("content-type") ?? "";
  let b: any = {};
  let image: File | null = null;

  if (type.includes("multipart/form-data")) {
    const form = await req.formData();
    for (const [k, v] of form.entries()) {
      if (v instanceof File) image = v;
      else b[k] = v;
    }
    if (typeof b.orderDetails === "string") {
      try { b.orderDetails = JSON.parse(b.orderDetails); } catch { b.orderDetails = []; }
    }
  } else {
    b = await req.json();
  }

  if (!b.order_code) return err(400, "order_code is required");

  let imageKey: string | null = null;
  if (image && env.IMAGES) {
    imageKey = `orders/${b.order_code}-${Date.now()}.jpg`;
    await env.IMAGES.put(imageKey, image.stream(), {
      httpMetadata: { contentType: image.type || "image/jpeg" },
    });
  }

  const id = oid();
  const stmts = [
    env.DB.prepare(
      `INSERT INTO orders (id, order_code, shelf_id, total_bill, status,
         customer_image, createdAt, updatedAt) VALUES (?,?,?,?,?,?,?,?)`
    ).bind(id, b.order_code, b.shelf_id ?? "", Number(b.total_bill ?? 0),
      b.status ?? "pending", imageKey, nowIso(), nowIso()),
  ];
  for (const d of (b.orderDetails ?? []) as any[]) {
    stmts.push(env.DB.prepare(
      `INSERT INTO order_details (id, order_id, product_id, quantity, price, total_price)
       VALUES (?,?,?,?,?,?)`
    ).bind(oid(), id, d.product_id ?? null, Number(d.quantity ?? 0),
      Number(d.price ?? 0), Number(d.total_price ?? 0)));
  }
  await env.DB.batch(stmts);

  return json({ message: "Order created successfully", id, _id: id,
    order_code: b.order_code }, 201);
};

const ordersList = async ({ env, url }: Ctx) => {
  const limit = Math.min(Number(url.searchParams.get("limit") ?? 100), 500);
  const list = await listAll(env,
    "SELECT * FROM orders ORDER BY createdAt DESC LIMIT ?", limit);
  const out = await Promise.all(list.map(async (o: any) => ({
    ...withMongoId(o),
    orderDetails: rows(await listAll(env,
      `SELECT od.*, p.product_name FROM order_details od
       LEFT JOIN products p ON p.id = od.product_id WHERE od.order_id = ?`, o.id)),
  })));
  return json(out);
};

const orderGet = async ({ env, params }: Ctx) => {
  const o = await env.DB.prepare("SELECT * FROM orders WHERE id = ?").bind(params.id).first<any>();
  if (!o) return err(404, "Order not found");
  const details = await listAll(env,
    `SELECT od.*, p.product_name FROM order_details od
     LEFT JOIN products p ON p.id = od.product_id WHERE od.order_id = ?`, o.id);
  return json({ ...withMongoId(o), orderDetails: rows(details) });
};

/* statistics -------------------------------------------------------------- */

const statsRevenue = async ({ env }: Ctx) =>
  json(await listAll(env,
    `SELECT date(createdAt) AS date, COUNT(*) AS orders, SUM(total_bill) AS revenue
     FROM orders WHERE status = 'paid'
     GROUP BY date(createdAt) ORDER BY date DESC LIMIT 30`));

const statsTopProducts = async ({ env }: Ctx) =>
  json(await listAll(env,
    `SELECT p.id, p.id AS _id, p.product_name, p.img_url,
            SUM(od.quantity) AS sold, SUM(od.total_price) AS revenue
     FROM order_details od
     JOIN orders o ON o.id = od.order_id AND o.status = 'paid'
     LEFT JOIN products p ON p.id = od.product_id
     GROUP BY od.product_id ORDER BY sold DESC LIMIT 10`));

/* histories --------------------------------------------------------------- */

/** The Jetson posts a restock record after an employee finishes refilling. */
const historyCreate = async ({ env, req }: Ctx) => {
  const b = (await req.json()) as any;
  const id = oid();
  const jsonOrNull = (v: unknown) => (v == null ? null : JSON.stringify(v));
  await env.DB.prepare(
    `INSERT INTO histories (id, shelf, user, user_rfid, notes, pre_products,
       post_products, pre_verified_quantity, post_verified_quantity,
       createdAt, updatedAt) VALUES (?,?,?,?,?,?,?,?,?,?,?)`
  ).bind(id, b.shelf ?? null, b.user ?? null, b.user_rfid ?? null, b.notes ?? "",
    jsonOrNull(b.pre_products), jsonOrNull(b.post_products),
    jsonOrNull(b.pre_verified_quantity), jsonOrNull(b.post_verified_quantity),
    nowIso(), nowIso()).run();
  return json({ message: "History added data posted successfully", id, _id: id }, 201);
};

const parseJsonCols = (r: any) => {
  for (const c of ["pre_products", "post_products",
    "pre_verified_quantity", "post_verified_quantity"]) {
    if (typeof r[c] === "string") { try { r[c] = JSON.parse(r[c]); } catch { /* keep raw */ } }
  }
  return r;
};

const historiesList = async ({ env, url }: Ctx) => {
  const limit = Math.min(Number(url.searchParams.get("limit") ?? 100), 500);
  const list = await listAll(env,
    `SELECT h.*, s.shelf_name, u.fullName AS user_name FROM histories h
     LEFT JOIN shelves s ON s.id = h.shelf
     LEFT JOIN users u   ON u.id = h.user
     ORDER BY h.createdAt DESC LIMIT ?`, limit);
  return json(rows(list.map(parseJsonCols)));
};

/* notifications ----------------------------------------------------------- */

const notificationsList = async ({ env, url }: Ctx) => {
  const limit = Math.min(Number(url.searchParams.get("limit") ?? 100), 500);
  return json(rows(await listAll(env,
    "SELECT * FROM notifications ORDER BY timestamp DESC LIMIT ?", limit)));
};

const notificationsUnread = async ({ env }: Ctx) => {
  const r = await env.DB.prepare(
    "SELECT COUNT(*) AS count FROM notifications WHERE read = 0").first<any>();
  return json({ count: r?.count ?? 0 });
};

const notificationCreate = async ({ env, req }: Ctx) => {
  const b = (await req.json()) as any;
  if (!b?.message) return err(400, "message is required");
  const id = oid();
  await env.DB.prepare(
    `INSERT INTO notifications (id, message, type, category, timestamp, read,
       shelf_id, load_cell_id, product_id, user_id) VALUES (?,?,?,?,?,?,?,?,?,?)`
  ).bind(id, b.message, b.type ?? "info", b.category ?? "general", nowIso(), 0,
    b.shelf_id ?? null, b.load_cell_id ?? null, b.product_id ?? null,
    b.user_id ?? null).run();
  return json({ id, _id: id, message: b.message }, 201);
};

const notificationRead = async ({ env, params }: Ctx) => {
  await env.DB.prepare("UPDATE notifications SET read = 1 WHERE id = ?").bind(params.id).run();
  return json({ message: "Marked as read" });
};

const notificationsReadAll = async ({ env }: Ctx) => {
  const r = await env.DB.prepare("UPDATE notifications SET read = 1 WHERE read = 0").run();
  return json({ message: "All marked as read", updated: r.meta.changes });
};

/* tasks ------------------------------------------------------------------- */

const tasksList = async ({ env }: Ctx) =>
  json(rows(await listAll(env,
    `SELECT t.*, ub.fullName AS assignedByName, ut.fullName AS assignedToName
     FROM tasks t
     LEFT JOIN users ub ON ub.id = t.assignedBy
     LEFT JOIN users ut ON ut.id = t.assignedTo
     ORDER BY t.createdAt DESC`)));

const taskCreate = async ({ env, req }: Ctx) => {
  const b = (await req.json()) as any;
  if (!b?.title) return err(400, "title is required");
  const id = oid();
  await env.DB.prepare(
    `INSERT INTO tasks (id, title, description, assignedBy, assignedTo, status,
       dueDate, createdAt, updatedAt) VALUES (?,?,?,?,?,?,?,?,?)`
  ).bind(id, b.title, b.description ?? null, b.assignedBy ?? null,
    b.assignedTo ?? null, b.status ?? "pending", b.dueDate ?? null,
    nowIso(), nowIso()).run();
  return json({ id, _id: id, title: b.title }, 201);
};

const taskUpdate = async ({ env, req, params }: Ctx) => {
  const b = (await req.json()) as any;
  const allowed = ["title", "description", "assignedTo", "status", "dueDate"];
  const sets: string[] = [], vals: unknown[] = [];
  for (const f of allowed) if (f in b) { sets.push(`${f} = ?`); vals.push(b[f]); }
  if (!sets.length) return err(400, "No updatable fields supplied");
  sets.push("updatedAt = ?"); vals.push(nowIso(), params.id);
  const r = await env.DB.prepare(`UPDATE tasks SET ${sets.join(", ")} WHERE id = ?`)
    .bind(...vals).run();
  return r.meta.changes ? json({ message: "Task updated" }) : err(404, "Task not found");
};

const taskDelete = async ({ env, params }: Ctx) => {
  const r = await env.DB.prepare("DELETE FROM tasks WHERE id = ?").bind(params.id).run();
  return r.meta.changes ? json({ message: "Task deleted" }) : err(404, "Task not found");
};

/* images ------------------------------------------------------------------ */

/** Serve customer photos stored in R2 (customer_image holds the object key). */
const imageGet = async ({ env, params }: Ctx) => {
  if (!env.IMAGES) return err(503, "Image storage not configured");
  const obj = await env.IMAGES.get(decodeURIComponent(params.key));
  if (!obj) return err(404, "Image not found");
  return new Response(obj.body, {
    headers: {
      ...CORS,
      "Content-Type": obj.httpMetadata?.contentType ?? "image/jpeg",
      "Cache-Control": "public, max-age=31536000",
    },
  });
};

/* ----------------------------------------------------------------- router */

type Handler = (ctx: Ctx) => Promise<Response> | Response;

const ROUTES: Array<[string, string, Handler]> = [
  ["GET", "/api/health", () => json({ status: "healthy" })],

  ["POST", "/api/users/login", login],
  ["POST", "/api/users/register", register],
  ["GET", "/api/users", usersList],
  ["POST", "/api/users", register],
  ["DELETE", "/api/users/:id", userDelete],

  ["GET", "/api/products", productsList],
  ["POST", "/api/products", productCreate],
  ["GET", "/api/products/:id", productGet],
  ["PUT", "/api/products/:id", productUpdate],
  ["DELETE", "/api/products/:id", productDelete],

  // Specific shelf routes must precede /api/shelves/:id
  ["GET", "/api/shelves/get-products/:shelfId", shelfProducts],
  ["GET", "/api/shelves/get-employee/:shelfId", shelfEmployees],
  ["GET", "/api/shelves/get-qr/:shelfId", shelfQr],
  ["GET", "/api/shelves/get-loadcell/:shelfId", shelfLoadcells],
  ["GET", "/api/shelves", shelvesList],
  ["GET", "/api/shelves/:id", shelfGet],

  ["GET", "/api/loadcell", loadcellsList],
  ["PUT", "/api/loadcell/:id", loadcellUpdate],
  ["PATCH", "/api/loadcell/:id/quantity-threshold", loadcellUpdate],
  ["PATCH", "/api/loadcell/:id/upload-quantity", loadcellUpdate],

  ["GET", "/api/combos", combosList],
  ["POST", "/api/combos", comboCreate],
  ["DELETE", "/api/combos/:id", comboDelete],

  ["GET", "/api/posters", postersList],
  ["POST", "/api/posters", posterCreate],
  ["DELETE", "/api/posters/:id", posterDelete],

  ["GET", "/api/sepay-config/shelf/:shelfId", sepayForShelf],
  ["PUT", "/api/sepay-config/shelf/:shelfId", sepayUpsert],
  ["POST", "/api/sepay-config/shelf/:shelfId", sepayUpsert],

  ["POST", "/api/orders", orderCreate],
  ["GET", "/api/orders", ordersList],
  ["GET", "/api/orders/statistics/revenue", statsRevenue],
  ["GET", "/api/orders/statistics/top-products", statsTopProducts],
  ["GET", "/api/orders/:id", orderGet],

  ["POST", "/api/histories", historyCreate],
  ["GET", "/api/histories", historiesList],

  ["GET", "/api/notifications", notificationsList],
  ["POST", "/api/notifications", notificationCreate],
  ["GET", "/api/notifications/unread-count", notificationsUnread],
  ["PATCH", "/api/notifications/mark-all-read", notificationsReadAll],
  ["PATCH", "/api/notifications/:id/read", notificationRead],

  ["GET", "/api/tasks", tasksList],
  ["POST", "/api/tasks", taskCreate],
  ["PUT", "/api/tasks/:id", taskUpdate],
  ["DELETE", "/api/tasks/:id", taskDelete],

  ["GET", "/api/images/:key", imageGet],
];

/** Match "/api/products/:id" against a concrete path. */
function match(pattern: string, path: string): Record<string, string> | null {
  const p = pattern.split("/"), a = path.split("/");
  if (p.length !== a.length) return null;
  const params: Record<string, string> = {};
  for (let i = 0; i < p.length; i++) {
    if (p[i].startsWith(":")) params[p[i].slice(1)] = decodeURIComponent(a[i]);
    else if (p[i] !== a[i]) return null;
  }
  return params;
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });

    const url = new URL(req.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    for (const [method, pattern, handler] of ROUTES) {
      if (method !== req.method) continue;
      const params = match(pattern, path);
      if (!params) continue;
      try {
        return await handler({ env, req, params, url });
      } catch (e: any) {
        return err(500, "Internal error", e?.message ?? String(e));
      }
    }
    return err(404, "Not found", `${req.method} ${path}`);
  },
} satisfies ExportedHandler<Env>;
