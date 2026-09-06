-- Smart Shelf CS17IUH - D1 schema
--
-- Ported from the Mongoose models in smart-shelf-server-backend. Notes:
--   * Mongo _id values are kept as TEXT ids so existing data (and the ids the
--     Jetson already has in its .env / local JSON) migrate over unchanged.
--   * SQLite has no DATE or BOOLEAN: timestamps are TEXT (ISO 8601) and flags
--     are INTEGER 0/1.
--   * Mongo arrays become join tables (shelf_users, combo_products).

-- ---------------------------------------------------------------- users
CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,
  rfid          TEXT UNIQUE,
  email         TEXT UNIQUE,
  password      TEXT NOT NULL,          -- bcrypt hash, same format as before
  fullName      TEXT,
  phone         TEXT,
  avatar        TEXT DEFAULT '',
  address       TEXT,
  dateOfBirth   TEXT,
  gender        TEXT CHECK (gender IN ('male','female','other')),
  role          TEXT NOT NULL DEFAULT 'employee'
                CHECK (role IN ('manager','admin','employee')),
  isActive      INTEGER NOT NULL DEFAULT 1,
  lastLogin     TEXT,
  emailVerified INTEGER NOT NULL DEFAULT 0,
  createdAt     TEXT NOT NULL DEFAULT (datetime('now')),
  updatedAt     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_users_rfid ON users(rfid);

-- --------------------------------------------------------------- shelves
CREATE TABLE IF NOT EXISTS shelves (
  id         TEXT PRIMARY KEY,
  shelf_id   TEXT NOT NULL UNIQUE,
  shelf_name TEXT NOT NULL UNIQUE,
  mac_ip     TEXT,
  location   TEXT,
  qr         TEXT,
  createdAt  TEXT NOT NULL DEFAULT (datetime('now')),
  updatedAt  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Mongo stored user_id as an array on the shelf.
CREATE TABLE IF NOT EXISTS shelf_users (
  shelf_id TEXT NOT NULL REFERENCES shelves(id) ON DELETE CASCADE,
  user_id  TEXT NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
  PRIMARY KEY (shelf_id, user_id)
);

-- -------------------------------------------------------------- products
CREATE TABLE IF NOT EXISTS products (
  id           TEXT PRIMARY KEY,
  product_id   TEXT,
  product_name TEXT NOT NULL,
  img_url      TEXT,
  price        REAL NOT NULL DEFAULT 0,
  discount     REAL NOT NULL DEFAULT 0,
  stock        INTEGER NOT NULL DEFAULT 0,
  weight       REAL NOT NULL DEFAULT 0,
  max_quantity INTEGER NOT NULL DEFAULT 1,
  threshold    INTEGER NOT NULL DEFAULT 1,
  createdAt    TEXT NOT NULL DEFAULT (datetime('now')),
  updatedAt    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------- loadcells
-- One row per shelf compartment (floor x column). This is what the Jetson's
-- 15 slots map onto.
CREATE TABLE IF NOT EXISTS loadcells (
  id                  TEXT PRIMARY KEY,
  load_cell_id        INTEGER NOT NULL,
  load_cell_name      TEXT,
  product_id          TEXT REFERENCES products(id) ON DELETE SET NULL,
  previous_product_id TEXT REFERENCES products(id) ON DELETE SET NULL,
  shelf_id            TEXT NOT NULL REFERENCES shelves(id) ON DELETE CASCADE,
  floor               INTEGER NOT NULL,
  column_index        INTEGER NOT NULL,   -- "column" is reserved-ish; keep it explicit
  threshold           INTEGER NOT NULL DEFAULT 1,
  quantity            INTEGER NOT NULL DEFAULT 0,
  error               INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_loadcells_shelf ON loadcells(shelf_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_loadcells_slot
  ON loadcells(shelf_id, floor, column_index);

-- ---------------------------------------------------------------- orders
CREATE TABLE IF NOT EXISTS orders (
  id             TEXT PRIMARY KEY,
  order_code     TEXT NOT NULL UNIQUE,
  shelf_id       TEXT NOT NULL,
  total_bill     REAL NOT NULL DEFAULT 0,
  status         TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','unpaid','paid','cancelled')),
  customer_image TEXT,
  createdAt      TEXT NOT NULL DEFAULT (datetime('now')),
  updatedAt      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(createdAt);
CREATE INDEX IF NOT EXISTS idx_orders_status  ON orders(status);

CREATE TABLE IF NOT EXISTS order_details (
  id          TEXT PRIMARY KEY,
  order_id    TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id  TEXT REFERENCES products(id) ON DELETE SET NULL,
  quantity    INTEGER NOT NULL,
  price       REAL NOT NULL,
  total_price REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_order_details_order ON order_details(order_id);

-- ---------------------------------------------------------------- combos
CREATE TABLE IF NOT EXISTS combos (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  description TEXT DEFAULT '',
  image       TEXT DEFAULT '',
  price       REAL NOT NULL DEFAULT 0,
  oldPrice    REAL NOT NULL DEFAULT 0,
  validFrom   TEXT,
  validTo     TEXT,
  createdAt   TEXT NOT NULL DEFAULT (datetime('now')),
  updatedAt   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS combo_products (
  combo_id   TEXT NOT NULL REFERENCES combos(id)   ON DELETE CASCADE,
  product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  PRIMARY KEY (combo_id, product_id)
);

-- --------------------------------------------------------------- posters
CREATE TABLE IF NOT EXISTS posters (
  id        TEXT PRIMARY KEY,
  image_url TEXT NOT NULL,
  createdAt TEXT NOT NULL DEFAULT (datetime('now')),
  updatedAt TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------- sepay configs
CREATE TABLE IF NOT EXISTS sepay_configs (
  id                 TEXT PRIMARY KEY,
  shelf_id           TEXT REFERENCES shelves(id) ON DELETE CASCADE,
  vietqrAccountNo    TEXT,
  vietqrAccountName  TEXT,
  vietqrAcqId        TEXT,               -- bank BIN, e.g. 970407 = Techcombank
  sepayAuthToken     TEXT,
  sepayBankAccountId TEXT,
  apiKey             TEXT,
  apiSecret          TEXT,
  merchantCode       TEXT,
  webhookUrl         TEXT,
  callbackUrl        TEXT,
  sandbox            INTEGER NOT NULL DEFAULT 1,
  active             INTEGER NOT NULL DEFAULT 1,
  createdAt          TEXT NOT NULL DEFAULT (datetime('now')),
  updatedAt          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sepay_shelf ON sepay_configs(shelf_id);

-- --------------------------------------------------------- notifications
CREATE TABLE IF NOT EXISTS notifications (
  id           TEXT PRIMARY KEY,
  message      TEXT NOT NULL,
  type         TEXT NOT NULL DEFAULT 'info'
               CHECK (type IN ('warning','error','info','success')),
  category     TEXT NOT NULL DEFAULT 'general'
               CHECK (category IN ('vibration','restock','low_stock','order','general')),
  timestamp    TEXT NOT NULL DEFAULT (datetime('now')),
  read         INTEGER NOT NULL DEFAULT 0,
  shelf_id     TEXT REFERENCES shelves(id)  ON DELETE SET NULL,
  load_cell_id TEXT REFERENCES loadcells(id) ON DELETE SET NULL,
  product_id   TEXT REFERENCES products(id) ON DELETE SET NULL,
  user_id      TEXT REFERENCES users(id)    ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read);
CREATE INDEX IF NOT EXISTS idx_notifications_time ON notifications(timestamp);

-- ----------------------------------------------------------------- tasks
CREATE TABLE IF NOT EXISTS tasks (
  id          TEXT PRIMARY KEY,
  title       TEXT NOT NULL,
  description TEXT,
  assignedBy  TEXT REFERENCES users(id) ON DELETE SET NULL,
  assignedTo  TEXT REFERENCES users(id) ON DELETE SET NULL,
  status      TEXT NOT NULL DEFAULT 'pending'
              CHECK (status IN ('pending','in_progress','completed','cancelled')),
  dueDate     TEXT,
  createdAt   TEXT NOT NULL DEFAULT (datetime('now')),
  updatedAt   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tasks_assignedTo ON tasks(assignedTo);

-- ------------------------------------------------------------- histories
-- Restock history: which employee refilled which shelf, and the before/after
-- product + quantity per slot (stored as JSON to mirror the Mongo arrays).
CREATE TABLE IF NOT EXISTS histories (
  id                     TEXT PRIMARY KEY,
  shelf                  TEXT REFERENCES shelves(id) ON DELETE SET NULL,
  user                   TEXT REFERENCES users(id)   ON DELETE SET NULL,
  user_rfid              TEXT,
  notes                  TEXT DEFAULT '',
  pre_products           TEXT,   -- JSON array
  post_products          TEXT,   -- JSON array
  pre_verified_quantity  TEXT,   -- JSON array
  post_verified_quantity TEXT,   -- JSON array
  createdAt              TEXT NOT NULL DEFAULT (datetime('now')),
  updatedAt              TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_histories_created ON histories(createdAt);
