import { readFile } from "node:fs/promises";

if (process.versions.node.split(".")[0] !== "22") {
  throw new Error(`Frontend commands require Node 22, received ${process.versions.node}`);
}
const rootTypeScript = JSON.parse(
  await readFile(new URL("../node_modules/typescript/package.json", import.meta.url), "utf8"),
);
if (rootTypeScript.version !== "6.0.3") {
  throw new Error("Application TypeScript must resolve to 6.0.3");
}
process.stdout.write(
  `Node ${process.versions.node}; application TypeScript 6.0.3\n`,
);
