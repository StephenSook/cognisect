import ledger from "../../../data/provenance/public-cases.v1.json";

export type PublicEducatorCase = (typeof ledger.records)[number];

export const PUBLIC_EDUCATOR_CASES: readonly PublicEducatorCase[] = ledger.records;
export const DEFAULT_PUBLIC_EDUCATOR_CASE = PUBLIC_EDUCATOR_CASES[0]!;
