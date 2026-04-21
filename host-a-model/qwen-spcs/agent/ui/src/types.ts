export type MessageRole = "user" | "assistant";

export type ToolStatus = "pending" | "done" | "error";

export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  result?: string;
  status: ToolStatus;
  downstreamStatus?: string;
  streamingContent?: string;
}

export interface TokenUsage {
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  toolCalls?: ToolCall[];
  isStreaming?: boolean;
  tokenUsage?: TokenUsage;
  latencyMs?: number;
}

export interface ChatEvent {
  type: "token" | "tool_call" | "tool_result" | "usage" | "done" | "downstream_token" | "downstream_status" | "heartbeat";
  content: string;
  metadata: Record<string, unknown>;
}
