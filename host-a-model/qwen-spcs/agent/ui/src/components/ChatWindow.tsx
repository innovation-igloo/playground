import type { ChatMessage } from "../types";
import { MessageBubble } from "./MessageBubble";
import { SnowflakeMark } from "./SnowflakeMark";
import { useEffect, useRef, useCallback } from "react";

interface Props {
  messages: ChatMessage[];
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full px-6 text-center">
      <div className="relative mb-5">
        <div className="absolute inset-0 rounded-full bg-snowflake-cyan/20 blur-2xl" />
        <SnowflakeMark className="relative h-14 w-14 text-snowflake-cyan" />
      </div>
      <h2 className="text-xl font-semibold tracking-tight text-snowflake-ink">
        Snowflake Multi-Agent Studio
      </h2>
      <p className="mt-2 text-sm text-snowflake-slate max-w-md">
        Self-hosted LLM on Snowpark Container Services, orchestrating Cortex
        Agents in your Snowflake account. Ask a question — it will be routed
        to the right Cortex Agent.
      </p>
    </div>
  );
}

export function ChatWindow({ messages }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const userScrolledUp = useRef(false);

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    userScrolledUp.current = distanceFromBottom > 80;
  }, []);

  useEffect(() => {
    if (!userScrolledUp.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      className="flex-1 overflow-y-auto px-4 py-6"
    >
      <div className="max-w-4xl mx-auto space-y-4 min-h-full pb-6">
        {messages.length === 0 ? (
          <EmptyState />
        ) : (
          messages.map((msg) => <MessageBubble key={msg.id} message={msg} />)
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
