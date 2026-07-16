import type { RefObject } from "react";

export function mutationKey(reference: RefObject<string | null>): string {
  reference.current ??= crypto.randomUUID();
  return reference.current;
}
