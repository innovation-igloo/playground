import { useState, useCallback, useRef } from "react";
import type { ChatMessage, ChatEvent, ToolCall, TokenUsage } from "../types";

const nextId = () => crypto.randomUUID();

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [threadId] = useState(() => crypto.randomUUID());
  const abortRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback(
    async (text: string, backend: "rest" | "cortex_agents" = "rest") => {
      if (!text.trim() || isLoading) return;

      const userMsg: ChatMessage = {
        id: nextId(),
        role: "user",
        content: text,
      };
      const assistantId = nextId();
      const assistantMsg: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        toolCalls: [],
        isStreaming: true,
      };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setIsLoading(true);

      const controller = new AbortController();
      abortRef.current = controller;
      const startTime = performance.now();

      try {
        const res = await fetch("/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text, thread_id: threadId, backend }),
          signal: controller.signal,
        });

        if (!res.ok || !res.body) {
          throw new Error(`Server error: ${res.status}`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const raw = line.slice(6).trim();
            if (!raw) continue;

            let event: ChatEvent;
            try {
              event = JSON.parse(raw);
            } catch {
              continue;
            }

            setMessages((prev) => {
              const updated = [...prev];
              const idx = updated.findIndex((m) => m.id === assistantId);
              if (idx === -1) return prev;

              const msg = { ...updated[idx] };

              if (event.type === "token") {
                msg.content += event.content;
              } else if (event.type === "downstream_token") {
                if (msg.toolCalls && msg.toolCalls.length > 0) {
                  const updatedCalls = [...msg.toolCalls];
                  for (let i = updatedCalls.length - 1; i >= 0; i--) {
                    if (updatedCalls[i].status === "pending") {
                      updatedCalls[i] = {
                        ...updatedCalls[i],
                        streamingContent: (updatedCalls[i].streamingContent || "") + event.content,
                      };
                      break;
                    }
                  }
                  msg.toolCalls = updatedCalls;
                }
              } else if (event.type === "downstream_status") {
                if (msg.toolCalls && msg.toolCalls.length > 0) {
                  const updatedCalls = [...msg.toolCalls];
                  for (let i = updatedCalls.length - 1; i >= 0; i--) {
                    if (updatedCalls[i].status === "pending") {
                      updatedCalls[i] = { ...updatedCalls[i], downstreamStatus: event.content };
                      break;
                    }
                  }
                  msg.toolCalls = updatedCalls;
                }
              } else if (event.type === "tool_call") {
                const tc: ToolCall = {
                  name: event.content,
                  args: (event.metadata?.args as Record<string, unknown>) || {},
                  status: "pending",
                };
                msg.toolCalls = [...(msg.toolCalls || []), tc];
              } else if (event.type === "tool_result") {
                if (msg.toolCalls && msg.toolCalls.length > 0) {
                  const updatedCalls = [...msg.toolCalls];
                  for (let i = updatedCalls.length - 1; i >= 0; i--) {
                    if (updatedCalls[i].status === "pending") {
                      updatedCalls[i] = { ...updatedCalls[i], status: "done" };
                      break;
                    }
                  }
                  msg.toolCalls = updatedCalls;
                }
              } else if (event.type === "usage") {
                msg.tokenUsage = event.metadata as unknown as TokenUsage;
              } else if (event.type === "done") {
                msg.isStreaming = false;
                msg.latencyMs = Math.round(performance.now() - startTime);
              }

              updated[idx] = msg;
              return updated;
            });
          }
        }
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== assistantId) return m;
            const failedCalls = m.toolCalls?.map((tc) =>
              tc.status === "pending" ? { ...tc, status: "error" as const } : tc,
            );
            return {
              ...m,
              content: m.content || "Connection error. Please try again.",
              isStreaming: false,
              toolCalls: failedCalls,
            };
          }),
        );
      } finally {
        setIsLoading(false);
        abortRef.current = null;
      }
    },
    [isLoading, threadId],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const clear = useCallback(() => {
    setMessages([]);
  }, []);

  return { messages, isLoading, sendMessage, stop, clear };
}
