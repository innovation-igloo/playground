interface Props {
  value: "rest" | "cortex_agents";
  onChange: (v: "rest" | "cortex_agents") => void;
}

const OPTIONS: { value: "rest" | "cortex_agents"; label: string; title: string }[] = [
  { value: "rest", label: "Analyst", title: "Cortex Analyst REST + Snowpark SQL" },
  { value: "cortex_agents", label: "Agent", title: "Cortex Agents :run endpoint" },
];

export function BackendToggle({ value, onChange }: Props) {
  return (
    <div className="inline-flex items-center gap-0.5 rounded-full bg-snowflake-sky border border-snowflake-ice p-0.5">
      {OPTIONS.map((opt) => {
        const active = value === opt.value;
        return (
          <button
            key={opt.value}
            title={opt.title}
            onClick={() => onChange(opt.value)}
            className={[
              "rounded-full px-3 py-1 text-xs font-semibold transition-all duration-150 focus:outline-none",
              active
                ? "bg-snowflake-blue text-white shadow-sm"
                : "text-snowflake-slate hover:text-snowflake-ink",
            ].join(" ")}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
