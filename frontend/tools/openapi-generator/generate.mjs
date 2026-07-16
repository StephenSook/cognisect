import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import openapiTS, { astToString } from "openapi-typescript";
import typeScriptPackage from "typescript/package.json" with { type: "json" };

if (typeScriptPackage.version !== "5.9.3") {
  throw new Error("OpenAPI generation requires workspace TypeScript 5.9.3");
}

const openapiUrl = new URL("../../../openapi/openapi.json", import.meta.url);
const outputUrl = new URL("../../src/lib/api/schema.d.ts", import.meta.url);
const ast = await openapiTS(await readFile(openapiUrl));
const generated = astToString(ast);

if (process.argv.includes("--check")) {
  let checkedIn = "";
  try {
    checkedIn = await readFile(outputUrl, "utf8");
  } catch {
    process.stderr.write("Generated API schema is missing. Run npm run generate:api.\n");
    process.exitCode = 1;
  }
  if (checkedIn && checkedIn !== generated) {
    process.stderr.write("Generated API schema is stale. Run npm run generate:api.\n");
    process.exitCode = 1;
  }
} else {
  await mkdir(new URL(".", outputUrl), { recursive: true });
  await writeFile(outputUrl, generated, "utf8");
  process.stdout.write(`Generated ${fileURLToPath(outputUrl)}\n`);
}
