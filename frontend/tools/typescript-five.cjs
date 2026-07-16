const Module = require("node:module");
const path = require("node:path");

const typeScriptFive = path.join(
  __dirname,
  "openapi-generator",
  "node_modules",
  "typescript",
  "lib",
  "typescript.js",
);
const originalResolveFilename = Module._resolveFilename;

Module._resolveFilename = function resolveFilename(request, parent, isMain, options) {
  if (request === "typescript") return typeScriptFive;
  return originalResolveFilename.call(this, request, parent, isMain, options);
};
