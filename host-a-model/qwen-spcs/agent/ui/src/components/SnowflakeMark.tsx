interface Props {
  className?: string;
}

export function SnowflakeMark({ className = "" }: Props) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 64 64"
      fill="none"
      stroke="currentColor"
      strokeWidth={3}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <line x1="32" y1="4" x2="32" y2="60" />
      <line x1="8" y1="18" x2="56" y2="46" />
      <line x1="8" y1="46" x2="56" y2="18" />
      <polyline points="32,4 28,10 32,14 36,10 32,4" />
      <polyline points="32,60 28,54 32,50 36,54 32,60" />
      <polyline points="8,18 14,18 14,24" />
      <polyline points="56,46 50,46 50,40" />
      <polyline points="8,46 14,46 14,40" />
      <polyline points="56,18 50,18 50,24" />
    </svg>
  );
}
