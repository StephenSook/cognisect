import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterAll, describe, expect, it } from "vitest";

const wrongNpmRoot = mkdtempSync(join(tmpdir(), "cognisect-wrong-npm-"));
mkdirSync(join(wrongNpmRoot, "bin"));
writeFileSync(join(wrongNpmRoot, "package.json"), '{"version":"11.16.0"}\n');

afterAll(() => rmSync(wrongNpmRoot, { recursive: true }));

function runToolchainCheck(npmExecPath: string) {
  return spawnSync(process.execPath, ["scripts/check-toolchain.mjs"], {
    cwd: process.cwd(),
    encoding: "utf8",
    env: {
      ...process.env,
      npm_config_user_agent: "npm/ignored",
      npm_execpath: npmExecPath,
    },
  });
}

describe("frontend toolchain custody", () => {
  it("accepts the exact npm release", () => {
    expect(process.env.npm_execpath).toBeTruthy();
    const result = runToolchainCheck(process.env.npm_execpath!);

    expect(result.status).toBe(0);
    expect(result.stdout).toContain("npm 10.9.4");
  });

  it("rejects a different npm release", () => {
    const result = runToolchainCheck(join(wrongNpmRoot, "bin", "npm-cli.js"));

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("npm 10.9.4");
  });
});
