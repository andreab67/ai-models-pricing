const assert = require("node:assert/strict");

const fs = require("node:fs");

const path = require("node:path");

const { test, after } = require("node:test");

const ts = require("typescript");

const { NextRequest } = require("next/server");

// Compile and execute the actual route in this isolated Node test process.
require.extensions[".ts"] = (module, filename) => {
  const { outputText } = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    fileName: filename,
  });

  module._compile(outputText, filename);
};

const { GET } = require(path.resolve(__dirname, "../src/app/api/[...path]/route.ts"));

const originalFetch = global.fetch;

const originalBase = process.env.API_BASE_URL;

const originalExpose = process.env.EXPOSE_ACCOUNT_DATA;

after(() => {
  global.fetch = originalFetch;

  for (const [key, value] of [["API_BASE_URL", originalBase],
                             ["EXPOSE_ACCOUNT_DATA", originalExpose]]) {
    if (value === undefined) delete process.env[key]; else process.env[key] = value;
  }
});

function request(segments, search = "") {
  return GET(new NextRequest(`https://dashboard.invalid/api/models${search}`),
             { params: Promise.resolve({ path: segments }) });
}

function stub(response = new Response("catalog", { headers: { "content-type": "application/json" } })) {
  const calls = [];
  global.fetch = async (...args) => { calls.push(args);

 return response; };

  return calls;
}

test("public route allowlist forwards only read-only data and strips refresh", async () => {
  process.env.API_BASE_URL = "http://backend.invalid:8000///";
  delete process.env.EXPOSE_ACCOUNT_DATA;

  for (const segments of [["models"], ["models", "top"], ["models", "org", "id"],
                          ["models", "org", "id", "history"], ["compare", "org", "id"],
                          ["kilo", "plans"], ["kilo", "models"], ["kilo", "models", "id"],
                          ["kilo", "projection"], ["healthz"]]) {
    const calls = stub();
    const response = await request(segments, "?refresh=true&refresh=false&limit=2&tag=a&tag=b");
    assert.equal(response.status, 200);
    assert.equal(await response.text(), "catalog");
    assert.equal(response.headers.get("cache-control"), "public, max-age=60");
    assert.equal(response.headers.get("content-type"), "application/json");
    assert.equal(calls.length, 1);
    const [url, options] = calls[0];
    assert.equal(url.origin, "http://backend.invalid:8000");
    assert.equal(url.searchParams.has("refresh"), false);
    assert.deepEqual(url.searchParams.getAll("tag"), ["a", "b"]);
    assert.equal(options.method, "GET");
    assert.equal(options.cache, "no-store");
    assert.equal(options.headers.accept, "application/json");
    assert.ok(options.signal instanceof AbortSignal);
  }
});

test("private routes and malformed segments never fetch", async () => {
  delete process.env.EXPOSE_ACCOUNT_DATA;
  const calls = stub();

  for (const segments of [["accounts", "usage"], ["accounts", "activity"], ["metrics"],
                          ["docs"], ["openapi.json"], ["readyz"], [], [""],
                          ["models", "..", "accounts", "usage"], ["models", "."],
                          ["models", "a/b"], ["models", ""]]) {
    const response = await request(segments);
    assert.equal(response.status, 404);
  }

  assert.equal(calls.length, 0);
});

test("explicit account opt-in forwards both paths without caching", async () => {
  process.env.EXPOSE_ACCOUNT_DATA = "TRUE";

  for (const endpoint of ["usage", "activity"]) {
    const calls = stub();
    const response = await request(["accounts", endpoint]);
    assert.equal(response.status, 200);
    assert.equal(calls.length, 1);
    assert.equal(response.headers.get("cache-control"), "no-store");
  }

  process.env.EXPOSE_ACCOUNT_DATA = "false";
});

test("upstream status propagates while errors and credentials are never cached or forwarded", async () => {
  stub(new Response("unavailable", { status: 503, headers: {
    "set-cookie": "private=value", "cache-control": "public, max-age=999", "x-private": "secret",
  }}));
  const response = await request(["models"]);
  assert.equal(response.status, 503);
  assert.equal(await response.text(), "unavailable");
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(response.headers.has("set-cookie"), false);
  assert.equal(response.headers.has("x-private"), false);
});

test("transport errors and timeouts have bounded public errors without caching", async () => {
  for (const [name, status, detail] of [["Error", 502, "Upstream unavailable"],
                                       ["TimeoutError", 504, "Upstream timeout"]]) {
    global.fetch = async () => { const error = new Error("private upstream details"); error.name = name; throw error; };

    const response = await request(["models"]);
    assert.equal(response.status, status);
    assert.deepEqual(await response.json(), { detail });
    assert.equal(response.headers.get("cache-control"), "no-store");
  }
});
