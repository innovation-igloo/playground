import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import type { ChatMessage } from "../types";
import { ToolCallCard } from "./ToolCallCard";
import { TokenPills } from "./TokenPills";
import { SnowflakePulse } from "./SnowflakePulse";

interface Props {
  message: ChatMessage;
}

export function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-br-md px-4 py-2.5 bg-snowflake-blue text-white shadow-sm">
          <div className="whitespace-pre-wrap text-[14px] leading-relaxed">
            {message.content}
          </div>
        </div>
      </div>
    );
  }

  const hasTools = message.toolCalls && message.toolCalls.length > 0;
  const showPulse =
    message.isStreaming && !message.content && !hasTools;

  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] w-full rounded-2xl rounded-bl-md px-4 py-3 bg-snowflake-cloud border border-snowflake-ice border-l-4 border-l-snowflake-cyan shadow-sm text-snowflake-ink">
        {hasTools && (
          <div className="mb-3 space-y-3">
            {message.toolCalls!.map((tc, i) => (
              <ToolCallCard
                key={i}
                toolCall={tc}
                isLast={i === message.toolCalls!.length - 1}
              />
            ))}
          </div>
        )}

        {message.content && (
          <div className="markdown-body text-[14px] leading-relaxed">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeHighlight]}
            >
              {message.content}
            </ReactMarkdown>
          </div>
        )}

        {showPulse && <SnowflakePulse />}

        {!message.isStreaming && (message.tokenUsage || message.latencyMs) && (
          <TokenPills usage={message.tokenUsage} latencyMs={message.latencyMs} />
        )}
      </div>
    </div>
  );
}
