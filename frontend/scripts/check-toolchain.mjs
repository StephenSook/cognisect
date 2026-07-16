import { readFile } from "node:fs/promises";

if (process.versions.node.split(".")[0] !== "22") {
  throw new Error(`Frontend commands require Node 22, received ${process.versions.node}`);
}
const rootTypeScript = JSON.parse(
  await readFile(new URL("../node_modules/typescript/package.json", import.meta.url), "utf8"),
);
const toolingTypeScript = JSON.parse(
  await readFile(
    new URL(
      "../tools/openapi-generator/node_modules/typescript/package.json",
      import.meta.url,
    ),
    "utf8",
  ),
);

if (rootTypeScript.version !== "7.0.2") {
  throw new Error("Application TypeScript must resolve to 7.0.2");
}
if (toolingTypeScript.version !== "5.9.3") {
  throw new Error("Compatibility tooling TypeScript must resolve to 5.9.3");
}
process.stdout.write(
  `Node ${process.versions.node}; application TypeScript 7.0.2; compatibility tooling TypeScript 5.9.3\n`,
);
