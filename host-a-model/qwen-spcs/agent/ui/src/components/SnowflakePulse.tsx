import { SnowflakeMark } from "./SnowflakeMark";

export function SnowflakePulse() {
  return (
    <div className="flex items-center gap-2 text-snowflake-cyan">
      <SnowflakeMark className="h-5 w-5 animate-snowflake-pulse" />
      <span className="text-xs text-snowflake-mist font-medium tracking-wide">Thinking...</span>
    </div>
  );
}
