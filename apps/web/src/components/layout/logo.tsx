export function Logo({ className = "" }: { className?: string }) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <svg viewBox="0 0 32 32" className="size-7" aria-hidden>
        <rect width="32" height="32" rx="8" className="fill-accent" />
        <path d="M9 22V10h14M9 16h10M9 22h14" fill="none" strokeWidth="2.6" strokeLinecap="round" className="stroke-accent-contrast" />
      </svg>
      <span className="text-base font-semibold tracking-tight">Evidentia</span>
    </div>
  );
}
