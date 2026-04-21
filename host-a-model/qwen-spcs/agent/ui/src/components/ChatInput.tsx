import { useState, type FormEvent, type KeyboardEvent } from "react";

interface Props {
  onSend: (message: string) => void;
  isLoading: boolean;
  onStop: () => void;
}

export function ChatInput({ onSend, isLoading, onStop }: Props) {
  const [input, setInput] = useState("");

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    onSend(input);
    setInput("");
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-snowflake-cloud border-t border-snowflake-ice p-4"
    >
      <div className="flex gap-3 max-w-4xl mx-auto">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask anything your Cortex Agent can answer..."
          rows={1}
          className="flex-1 resize-none rounded-xl bg-snowflake-frost border border-snowflake-ice px-4 py-3 text-[14px] text-snowflake-ink placeholder-snowflake-mist focus:outline-none focus:ring-2 focus:ring-snowflake-cyan focus:border-transparent transition-all"
        />
        {isLoading ? (
          <button
            type="button"
            onClick={onStop}
            className="px-5 py-3 rounded-xl bg-snowflake-coral hover:bg-red-500 text-white text-[13px] font-semibold transition-colors shadow-sm"
          >
            Stop
          </button>
        ) : (
          <button
            type="submit"
            disabled={!input.trim()}
            className="px-5 py-3 rounded-xl bg-snowflake-blue hover:bg-[#0e4a6d] disabled:bg-snowflake-ice disabled:text-snowflake-mist text-white text-[13px] font-semibold transition-all shadow-sm hover:shadow-[0_0_0_3px_rgba(41,181,232,0.25)]"
          >
            Send
          </button>
        )}
      </div>
      <div className="max-w-4xl mx-auto mt-2 text-[11px] text-snowflake-mist">
        Powered by Qwen hosted on Snowpark Container Services
      </div>
    </form>
  );
}
