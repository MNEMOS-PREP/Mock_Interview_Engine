import type { ReactNode } from "react";

/** The page opening from the design: a small green line, a large title, then what the page is for. */
export function PageIntro({
  kicker,
  title,
  subtitle,
  how,
}: {
  kicker: string;
  title: string;
  subtitle?: string;
  /** Longer help, kept behind a "How this works" fold. */
  how?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-3">
      <p className="text-[11px] uppercase leading-normal tracking-[1.6px] text-brand">{kicker}</p>
      <h1 className="text-[43px] font-medium leading-[1.15] tracking-[-1.8px] text-ink max-sm:text-[32px] max-sm:tracking-[-1.2px]">{title}</h1>
      {subtitle && <p className="max-w-2xl text-[15px] leading-[1.65] text-ink-soft">{subtitle}</p>}
      {how && (
        <details className="max-w-2xl text-xs leading-[1.7] text-ink-soft">
          <summary className="cursor-pointer text-[11px] font-semibold text-brand">How this works</summary>
          <div className="mt-2 flex flex-col gap-2">{how}</div>
        </details>
      )}
    </header>
  );
}
