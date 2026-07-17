"use client";

import QRCode from "qrcode";
import { useEffect, useState } from "react";

import { createBrowserApiClient } from "@/lib/api/browser-client";

type QrState =
  | { status: "checking" }
  | { status: "ready"; source: string }
  | { status: "unavailable" };

function learnerToken(learnerLink: string): string | null {
  try {
    const url = new URL(learnerLink, window.location.origin);
    if (url.origin !== window.location.origin) return null;
    const match = url.pathname.match(/^\/respond\/([^/]+)$/);
    return match?.[1] === undefined ? null : decodeURIComponent(match[1]);
  } catch {
    return null;
  }
}

export function LearnerQr({ learnerLink }: { learnerLink: string }) {
  const [state, setState] = useState<QrState>({ status: "checking" });

  useEffect(() => {
    let cancelled = false;

    async function verifyAndGenerate() {
      const token = learnerToken(learnerLink);
      if (token === null) {
        setState({ status: "unavailable" });
        return;
      }
      try {
        const result = await createBrowserApiClient().GET("/v1/respond/{token}", {
          params: { path: { token } },
          cache: "no-store",
        });
        if (result.data === undefined) throw new Error("learner smoke failed");
        const svg = await QRCode.toString(learnerLink, {
          type: "svg",
          errorCorrectionLevel: "M",
          margin: 1,
          width: 192,
          color: { dark: "#101313", light: "#fffef8" },
        });
        if (!cancelled) {
          setState({
            status: "ready",
            source: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`,
          });
        }
      } catch {
        if (!cancelled) setState({ status: "unavailable" });
      }
    }

    void verifyAndGenerate();
    return () => {
      cancelled = true;
    };
  }, [learnerLink]);

  if (state.status === "ready") {
    return (
      <figure className="learner-qr" aria-labelledby="learner-qr-caption">
        {/* A local data URL avoids sending the learner capability to a third party. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={state.source}
          alt="QR code for the learner response link"
          width="192"
          height="192"
        />
        <figcaption id="learner-qr-caption">
          <strong>QR transport ready.</strong>
          <span>Scan to open the same one-time learner link.</span>
        </figcaption>
      </figure>
    );
  }

  return (
    <p className="qr-status" role="status" aria-live="polite">
      {state.status === "checking"
        ? "Checking QR transport…"
        : "QR unavailable. Copy the learner link instead."}
    </p>
  );
}
