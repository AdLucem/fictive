/** Inline stroke icons, sized in the em-ish range the Material specs use. */

interface IconProps {
  size?: number;
}

const stroke = {
  fill: "none",
  strokeWidth: 1.7,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export function Chevron({ size = 14, className }: IconProps & { className?: string }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 12 12" aria-hidden="true">
      <path d="M4 2.5L8 6l-4 3.5" stroke="currentColor" {...stroke} />
    </svg>
  );
}

export function Arrow({ size = 13 }: IconProps) {
  return (
    <svg width={size} height={10} viewBox="0 0 12 10" aria-hidden="true">
      <path d="M1 5h9M7 2l3 3-3 3" stroke="currentColor" {...stroke} strokeWidth={1.4} />
    </svg>
  );
}

export function Check({ size = 12 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" aria-hidden="true">
      <path d="M2.5 6.4l2.4 2.4 4.6-5.2" stroke="currentColor" {...stroke} strokeWidth={1.6} />
    </svg>
  );
}

export function Bang({ size = 12 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" aria-hidden="true">
      <path d="M6 2.8v4M6 8.9v.2" stroke="currentColor" {...stroke} />
    </svg>
  );
}

export function Plus({ size = 18 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 18 18" aria-hidden="true">
      <path d="M9 3v12M3 9h12" stroke="currentColor" {...stroke} strokeWidth={2} />
    </svg>
  );
}

export function Search({ size = 17 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 18 18" aria-hidden="true">
      <circle cx="8" cy="8" r="5.2" stroke="currentColor" fill="none" strokeWidth={1.6} />
      <path d="M12 12l3.2 3.2" stroke="currentColor" {...stroke} strokeWidth={1.6} />
    </svg>
  );
}

export function Send({ size = 19 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 17 17" aria-hidden="true">
      <path d="M3 8.5h10M9 4.5l4 4-4 4" stroke="currentColor" {...stroke} strokeWidth={1.9} />
    </svg>
  );
}

export function Save({ size = 20 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" aria-hidden="true">
      <path
        d="M4 4.5h9.5L16 7v8.5a.5.5 0 01-.5.5h-11a.5.5 0 01-.5-.5v-11a.5.5 0 01.5-.5z"
        stroke="currentColor"
        fill="none"
        strokeWidth={1.6}
        strokeLinejoin="round"
      />
      <path d="M7 4.5V9h6" stroke="currentColor" fill="none" strokeWidth={1.6} strokeLinejoin="round" />
    </svg>
  );
}

export function Close({ size = 18 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" aria-hidden="true">
      <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" {...stroke} strokeWidth={1.6} />
    </svg>
  );
}

export function Stack({ size = 20 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true">
      <path d="M3 3.5h10M3 8h10M3 12.5h10" stroke="currentColor" fill="none" strokeWidth={1.5} strokeLinecap="round" />
    </svg>
  );
}

export function Lighthouse({ size = 20 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" aria-hidden="true">
      <path d="M3.5 17V4h10M3.5 10.5h8" stroke="currentColor" {...stroke} strokeWidth={1.9} />
      <circle cx="15" cy="14" r="2.5" stroke="currentColor" fill="none" strokeWidth={1.7} />
    </svg>
  );
}

export function Lines({ size = 15 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" aria-hidden="true">
      <path d="M2 3.5h10M2 7h10M2 10.5h6" stroke="currentColor" fill="none" strokeWidth={1.4} strokeLinecap="round" />
    </svg>
  );
}
