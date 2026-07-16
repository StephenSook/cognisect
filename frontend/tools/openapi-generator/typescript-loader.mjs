const workspaceTypeScriptUrl = new URL(
  "./node_modules/typescript/lib/typescript.js",
  import.meta.url,
).href;

export async function resolve(specifier, context, nextResolve) {
  if (
    specifier === "typescript" &&
    context.parentURL?.includes("/node_modules/openapi-typescript/")
  ) {
    return { url: workspaceTypeScriptUrl, shortCircuit: true };
  }
  return nextResolve(specifier, context);
}
