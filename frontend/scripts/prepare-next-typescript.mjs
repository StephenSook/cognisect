import { lstat, mkdir, realpath, symlink } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const compatibilityUrl = new URL(
  "../node_modules/typescript/lib/typescript.js",
  import.meta.url,
);
const toolingUrl = new URL(
  "../tools/openapi-generator/node_modules/typescript/lib/typescript.js",
  import.meta.url,
);

await mkdir(new URL(".", compatibilityUrl), { recursive: true });
try {
  const existing = await lstat(compatibilityUrl);
  if (!existing.isSymbolicLink()) {
    throw new Error("Refusing to replace an unexpected TypeScript compatibility file");
  }
  const [existingTarget, expectedTarget] = await Promise.all([
    realpath(compatibilityUrl),
    realpath(toolingUrl),
  ]);
  if (existingTarget !== expectedTarget) {
    throw new Error("TypeScript compatibility link points to an unexpected target");
  }
} catch (error) {
  if (!(error instanceof Error) || !("code" in error) || error.code !== "ENOENT") throw error;
  await symlink(fileURLToPath(toolingUrl), fileURLToPath(compatibilityUrl));
}
process.stdout.write("Next.js legacy TypeScript API mapped to tooling TypeScript 5.9.3\n");
