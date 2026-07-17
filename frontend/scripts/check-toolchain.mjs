import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const npmExecPath = process.env.npm_execpath;
if (npmExecPath === undefined) {
  throw new Error("Frontend commands must be invoked through npm 10.9.4");
}
const npmPackage = JSON.parse(
  await readFile(new URL("../package.json", pathToFileURL(npmExecPath)), "utf8"),
);
const npmVersion = npmPackage.version;
if (npmVersion !== "10.9.4") {
  throw new Error(`Frontend commands require npm 10.9.4, received ${npmVersion}`);
}
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
  `Node ${process.versions.node}; npm ${npmVersion}; application TypeScript 6.0.3\n`,
);
