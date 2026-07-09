const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const COPY_PATH = path.join(ROOT, "dashboard", "src", "content", "copy.csv");
const SRC_ROOT = path.join(ROOT, "dashboard", "src");

const REQUIRED_COLUMNS = ["key", "module", "page", "component", "slot", "text"];

function parseCsv(raw) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;

  for (let i = 0; i < raw.length; i += 1) {
    const ch = raw[i];

    if (inQuotes) {
      if (ch === '"') {
        const next = raw[i + 1];
        if (next === '"') {
          field += '"';
          i += 1;
        } else {
          inQuotes = false;
        }
      } else {
        field += ch;
      }
      continue;
    }

    if (ch === '"') {
      inQuotes = true;
      continue;
    }

    if (ch === ",") {
      row.push(field);
      field = "";
      continue;
    }

    if (ch === "\n") {
      row.push(field);
      field = "";
      if (!row.every((cell) => String(cell).trim() === "")) {
        rows.push(row);
      }
      row = [];
      continue;
    }

    if (ch === "\r") {
      continue;
    }

    field += ch;
  }

  row.push(field);
  if (!row.every((cell) => String(cell).trim() === "")) {
    rows.push(row);
  }

  return rows;
}

function readRegistry() {
  const raw = fs.readFileSync(COPY_PATH, "utf8");
  const rows = parseCsv(raw || "");
  if (!rows.length) {
    throw new Error(`Copy registry is empty: ${COPY_PATH}`);
  }

  const header = rows[0].map((cell) => String(cell).trim());
  const missing = REQUIRED_COLUMNS.filter((col) => !header.includes(col));
  if (missing.length) {
    throw new Error(`Copy registry missing columns: ${missing.join(", ")}`);
  }

  const idx = Object.fromEntries(header.map((col, index) => [col, index]));
  const entries = [];
  rows.slice(1).forEach((cells, rowIndex) => {
    const record = {
      key: String(cells[idx.key] || "").trim(),
      module: String(cells[idx.module] || "").trim(),
      page: String(cells[idx.page] || "").trim(),
      component: String(cells[idx.component] || "").trim(),
      slot: String(cells[idx.slot] || "").trim(),
      text: String(cells[idx.text] ?? "").trim(),
      row: rowIndex + 2,
    };
    if (!record.key) return;
    entries.push(record);
  });

  return entries;
}

function walkFiles(dir, results = []) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules") continue;
      walkFiles(fullPath, results);
      continue;
    }
    if (!entry.isFile()) continue;
    if (!/[.](js|jsx|ts|tsx)$/.test(entry.name)) continue;
    results.push(fullPath);
  }
  return results;
}

function extractKeys(source) {
  const keys = [];
  const regex = /\bcopy\(\s*['"]([^'"]+)['"]/g;
  let match;
  while ((match = regex.exec(source))) {
    keys.push(match[1]);
  }
  return keys;
}

function main() {
  const errors = [];
  const warnings = [];

  let registry = [];
  try {
    registry = readRegistry();
  } catch (err) {
    console.error(err.message);
    process.exit(1);
  }

  const registryMap = new Map();
  const duplicates = new Map();

  for (const record of registry) {
    if (registryMap.has(record.key)) {
      const list = duplicates.get(record.key) || [registryMap.get(record.key).row];
      list.push(record.row);
      duplicates.set(record.key, list);
    }
    registryMap.set(record.key, record);

    for (const col of REQUIRED_COLUMNS) {
      const value = record[col];
      if (!value || String(value).trim() === "") {
        errors.push(`Row ${record.row}: missing ${col} for key '${record.key || "<empty>"}'`);
        break;
      }
    }
  }

  for (const [key, rows] of duplicates.entries()) {
    errors.push(`Duplicate key '${key}' found on rows: ${rows.join(", ")}`);
  }

  const files = walkFiles(SRC_ROOT);
  const usedKeys = new Set();
  for (const file of files) {
    const content = fs.readFileSync(file, "utf8");
    extractKeys(content).forEach((key) => usedKeys.add(key));
  }

  for (const key of usedKeys) {
    if (!registryMap.has(key)) {
      errors.push(`Missing copy key '${key}' in copy.csv`);
    }
  }

  for (const key of registryMap.keys()) {
    if (!usedKeys.has(key)) {
      warnings.push(`Unused copy key '${key}'`);
    }
  }

  if (warnings.length) {
    console.warn("Copy registry warnings:");
    warnings.forEach((line) => console.warn(`- ${line}`));
  }

  if (errors.length) {
    console.error("Copy registry errors:");
    errors.forEach((line) => console.error(`- ${line}`));
    process.exit(1);
  }

  console.log(`Copy registry ok: ${registryMap.size} entries, ${usedKeys.size} keys used.`);
}

main();
