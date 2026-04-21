import { useState } from "react";
import { ChatWindow } from "./components/ChatWindow";
import { ChatInput } from "./components/ChatInput";
import { SnowflakeMark } from "./components/SnowflakeMark";
import { BackendToggle } from "./components/BackendToggle";
import { useChat } from "./hooks/useChat";

export default function App() {
  const { messages, isLoading, sendMessage, stop, clear } = useChat();
  const [backend, setBackend] = useState<"rest" | "cortex_agents">("rest");

  return (
    <div className="flex flex-col h-screen bg-snowflake-frost">
      <header className="flex items-center justify-between px-6 py-3.5 bg-snowflake-cloud border-b border-snowflake-ice">
        <div className="flex items-center gap-2.5">
          <SnowflakeMark className="h-6 w-6 text-snowflake-cyan" />
          <h1 className="text-[15px] font-semibold tracking-tight text-snowflake-ink">
            Snowflake Multi-Agent Studio
          </h1>
          <span className="ml-1 inline-flex h-1.5 w-1.5 rounded-full bg-snowflake-cyan shadow-[0_0_8px_rgba(41,181,232,0.8)]" />
        </div>
        <div className="flex items-center gap-3">
          <BackendToggle value={backend} onChange={setBackend} />
          <button
            onClick={clear}
            className="text-xs font-medium text-snowflake-slate hover:text-snowflake-blue px-3 py-1.5 rounded-md hover:bg-snowflake-sky transition-colors"
          >
            New chat
          </button>
        </div>
      </header>

      <ChatWindow messages={messages} />
      <ChatInput onSend={(text) => sendMessage(text, backend)} isLoading={isLoading} onStop={stop} />
    </div>
  );
}
