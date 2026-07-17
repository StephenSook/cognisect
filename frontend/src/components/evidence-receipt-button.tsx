export function EvidenceReceiptButton({ workflowId }: { workflowId: string }) {
  return (
    <form action={`/api/backend/v1/workflows/${workflowId}/receipt`} method="get">
      <button className="primary-button" type="submit">
        Download evidence receipt
      </button>
    </form>
  );
}
