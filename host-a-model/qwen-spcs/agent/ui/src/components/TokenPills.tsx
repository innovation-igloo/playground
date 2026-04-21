import type { ChatMessage } from "../types";

interface Props {
  usage?: ChatMessage["tokenUsage"];
  latencyMs?: number;
}

function formatLatency(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function Pill({
  icon,
  label,
  value,
  title,
}: {
  icon: string;
  label: string;
  value: string;
  title: string;
}) {
  return (
    <span
      title={title}
      className="inline-flex items-center gap-1 rounded-full bg-snowflake-sky border border-snowflake-ice px-2 py-0.5 text-[11px] font-medium text-snowflake-slate"
    >
      <span className="text-snowflake-cyan font-semibold">{icon}</span>
      <span className="text-snowflake-mist">{label}</span>
      <span className="font-mono text-snowflake-ink">{value}</span>
    </span>
  );
}

export function TokenPills({ usage, latencyMs }: Props) {
  const input = usage?.input_tokens ?? usage?.prompt_tokens ?? 0;
  const output = usage?.output_tokens ?? usage?.completion_tokens ?? 0;
  const total = usage?.total_tokens ?? input + output;

  if (!total && !latencyMs) return null;

  return (
    <div className="mt-3 pt-2.5 border-t border-snowflake-ice flex flex-wrap gap-1.5">
      {total > 0 && (
        <>
          <Pill icon="↑" label="in" value={input.toLocaleString()} title="Input tokens" />
          <Pill icon="↓" label="out" value={output.toLocaleString()} title="Output tokens" />
          <Pill icon="Σ" label="total" value={total.toLocaleString()} title="Total tokens" />
        </>
      )}
      {latencyMs != null && (
        <Pill icon="⏱" label="latency" value={formatLatency(latencyMs)} title="Round-trip latency" />
      )}
    </div>
  );
}
