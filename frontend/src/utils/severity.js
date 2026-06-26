// Centralized severity helpers. F-C3: the previous copy-pasted helpers
// (`severityBucket`, `severityColor`) in Dashboard.jsx and AlertTriggered.jsx
// compared strings against numbers (`'critical' >= 9` is always false), so
// every severity-driven color/badge silently rendered the "low" color.
// Accept either numeric 0–10 or a bucket string so the function works for
// both the dashboard's `by_severity` aggregation (numeric) and the
// triggered-alerts list (string bucket).

export const SEVERITY_RANK = { critical: 3, high: 2, medium: 1, low: 0 };

/**
 * Coerce a severity value (number 0-10 or bucket string) into a bucket.
 * Unknown / nullish values fall back to "low" rather than throwing.
 */
export function severityBucket(s) {
  if (typeof s === "number" && Number.isFinite(s)) {
    if (s >= 9) return "critical";
    if (s >= 7) return "high";
    if (s >= 4) return "medium";
    return "low";
  }
  if (typeof s === "string" && s in SEVERITY_RANK) return s;
  return "low";
}

/**
 * Map a severity value to a CSS color token. Falls back to hard-coded
 * hex so an unstyled theme still renders readably.
 */
export function severityColor(s) {
  return {
    critical: "var(--color-error, #dc2626)",
    high: "var(--color-accent-red, #dc2626)",
    medium: "var(--color-warning, #f59e0b)",
    low: "var(--color-accent-teal, #14b8a6)",
  }[severityBucket(s)];
}
