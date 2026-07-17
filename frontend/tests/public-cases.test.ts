import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";

import { PUBLIC_EDUCATOR_CASES } from "@/lib/public-cases";

describe("public educator-authored provenance ledger", () => {
  it("contains only display-cleared original content with a reproducible hash", () => {
    expect(PUBLIC_EDUCATOR_CASES).toHaveLength(6);
    expect(new Set(PUBLIC_EDUCATOR_CASES.map((record) => record.record_id)).size).toBe(6);

    for (const record of PUBLIC_EDUCATOR_CASES) {
      const canonicalContent = JSON.stringify({
        observed_work: record.content.observed_work,
        problem: record.content.problem,
      });

      expect(record.record_id).toMatch(/^cognisect-ea-00[1-6]$/);
      expect(record.tier).toBe("educator_authored");
      expect(record.authenticity).toBe("educator-authored");
      expect(record.source_url).toBeNull();
      expect(record.public_display_permitted).toBe(true);
      expect(record.redistribution_permitted).toBe(true);
      expect(createHash("sha256").update(canonicalContent).digest("hex")).toBe(
        record.content_sha256,
      );
    }
  });
});
