import { useState } from "react";
import type { ToolCall } from "../types";

interface Props {
  toolCall: ToolCall;
  isLast: boolean;
}

function StatusDot({ status }: { status: ToolCall["status"] }) {
  if (status === "pending") {
    return (
      <span className="relative z-10 flex h-3 w-3 items-center justify-center">
        <span className="absolute inline-flex h-full w-full rounded-full bg-snowflake-cyan opacity-70 animate-tool-ping" />
        <span className="relative inline-flex h-3 w-3 rounded-full bg-snowflake-cyan" />
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="relative z-10 inline-flex h-3 w-3 items-center justify-center rounded-full bg-snowflake-coral text-white text-[9px] font-bold">
        !
      </span>
    );
  }
  return (
    <span className="relative z-10 inline-flex h-3 w-3 items-center justify-center rounded-full bg-snowflake-blue text-white">
      <svg viewBox="0 0 12 12" className="h-2 w-2" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="2.5,6.5 5,9 9.5,3.5" />
      </svg>
    </span>
  );
}

function statusLabel(status: ToolCall["status"]): string {
  if (status === "pending") return "Running";
  if (status === "error") return "Failed";
  return "Complete";
}

export function ToolCallCard({ toolCall, isLast }: Props) {
  const [open, setOpen] = useState(false);
  const hasArgs = toolCall.args && Object.keys(toolCall.args).length > 0;

  return (
    <div className="relative pl-6">
      {!isLast && (
        <span
          aria-hidden="true"
          className="absolute left-[5px] top-3 bottom-[-12px] w-px bg-snowflake-ice"
        />
      )}
      <span className="absolute left-0 top-1">
        <StatusDot status={toolCall.status} />
      </span>

      <div className="rounded-lg bg-snowflake-frost border border-snowflake-ice px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-snowflake-cyan">
              Tool
            </span>
            <span className="font-mono text-[13px] font-semibold text-snowflake-blue">
              {toolCall.name}
            </span>
          </div>
          <span
            className={`text-[10px] font-medium uppercase tracking-wider ${
              toolCall.status === "pending"
                ? "text-snowflake-cyan"
                : toolCall.status === "error"
                  ? "text-snowflake-coral"
                  : "text-snowflake-slate"
            }`}
          >
            {statusLabel(toolCall.status)}
          </span>
        </div>

        {toolCall.status === "pending" && !toolCall.streamingContent && toolCall.downstreamStatus && (
          <p className="mt-1 text-[11px] text-snowflake-mist animate-pulse truncate">
            {toolCall.downstreamStatus}
          </p>
        )}

        {toolCall.status === "pending" && toolCall.streamingContent && (
          <div className="mt-2 max-h-40 overflow-y-auto rounded bg-white border border-snowflake-ice px-2 py-1.5">
            <p className="text-[12px] text-snowflake-ink whitespace-pre-wrap font-mono leading-relaxed">
              {toolCall.streamingContent}
              <span className="inline-block w-1.5 h-3 bg-snowflake-cyan ml-0.5 animate-pulse align-middle" />
            </p>
          </div>
        )}

        {hasArgs && (
          <button
            type="button"
            onClick={() => setOpen(!open)}
            className="mt-1 text-[11px] text-snowflake-mist hover:text-snowflake-blue transition-colors"
          >
            {open ? "▾ Hide arguments" : "▸ Show arguments"}
          </button>
        )}
        {hasArgs && open && (
          <pre className="mt-1.5 text-[11px] text-snowflake-slate overflow-x-auto bg-white border border-snowflake-ice rounded px-2 py-1.5 font-mono">
            {JSON.stringify(toolCall.args, null, 2)}
          </pre>
        )}

        {toolCall.result && (
          <div className="mt-2 pt-2 border-t border-snowflake-ice text-[13px] text-snowflake-ink whitespace-pre-wrap">
            {toolCall.result}
          </div>
        )}
      </div>
    </div>
  );
}
