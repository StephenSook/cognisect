import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";

import { PUBLIC_EDUCATOR_CASES } from "@/lib/public-cases";

describe("public educator-authored provenance ledger", () => {
  it("contains only display-cleared original content with a reproducible hash", () => {
    expect(PUBLIC_EDUCATOR_CASES).toHaveLength(1);
    const record = PUBLIC_EDUCATOR_CASES[0]!;
    const canonicalContent = JSON.stringify({
      observed_work: record.content.observed_work,
      problem: record.content.problem,
    });

    expect(record.record_id).toBe("cognisect-ea-001");
    expect(record.tier).toBe("educator_authored");
    expect(record.authenticity).toBe("educator-authored");
    expect(record.source_url).toBeNull();
    expect(record.public_display_permitted).toBe(true);
    expect(record.redistribution_permitted).toBe(true);
    expect(createHash("sha256").update(canonicalContent).digest("hex")).toBe(
      record.content_sha256,
    );
  });
});
