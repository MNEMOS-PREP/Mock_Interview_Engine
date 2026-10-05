/**
 * An interviewer's face, drawn rather than fetched (2026-10-04).
 *
 * Initials in a circle read as an account menu, not as a person across the
 * table. A face does, and it costs no network: the demo laptop with no Wi-Fi
 * draws the same panel. Everything is derived from the persona's name, so
 * Priya is the same person on the setup screen, the plan and in the room —
 * and nothing about how she looks says anything about how she marks.
 *
 * 2026-10-05: the face talks while the interviewer's voice speaks — a ring
 * says who is speaking, and the mouth opens on each word (`voice.ts` says how
 * far, every frame, without re-rendering the room). Under reduced motion the
 * ring stays and the mouth does not move.
 *
 * 2026-10-06: the hair follows the persona's own `voice_id` kind (authored in
 * the persona file, `en-IN-male-neutral`) — never guessed from the name. A
 * panel put Arjun's male voice under a face with long hair, and a voice and a
 * face that disagree read as two people.
 */
import { useEffect, useRef } from "react";

const REDUCED_MOTION =
  typeof window !== "undefined" &&
  typeof window.matchMedia === "function" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const BACKGROUNDS = ["#5b5bd6", "#0d9488", "#c2410c", "#7c3aed", "#0369a1", "#be185d"];
const SKIN = ["#f1c7a5", "#d9a37e", "#b97c56", "#8d5a3b", "#6b4228"];
const HAIR = ["#1f1a17", "#3b2a20", "#5a3b26", "#2b2b33", "#7a4a2a"];

/** The kind a persona's `voice_id` declares (`locale-kind-manner`), if any. */
export function voiceKind(voiceId: string | null | undefined): string | undefined {
  return /^[a-z]{2}-[A-Z]{2}-([a-z]+)-[a-z]+$/.exec(voiceId ?? "")?.[1];
}

function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function Face({
  name,
  size = 36,
  speaking = false,
  mouth,
  kind,
}: {
  name: string;
  size?: number;
  /** The persona file's declared kind ("female", "male"); the hair follows it. */
  kind?: string;
  /** The interviewer's voice is saying this person's line right now. */
  speaking?: boolean;
  /** How open the mouth is for a frame, 0 to 1 (`useInterviewerVoice`). */
  mouth?: (now: number) => number;
}) {
  const h = hash(name);
  const mouthShape = useRef<SVGEllipseElement>(null);
  const talking = speaking && mouth !== undefined && !REDUCED_MOTION;

  useEffect(() => {
    if (!talking || !mouth) return;
    let frame = 0;
    const draw = (now: number) => {
      const open = Math.min(1, Math.max(0, mouth(now)));
      mouthShape.current?.setAttribute("ry", (0.3 + 1.4 * open).toFixed(2));
      mouthShape.current?.setAttribute("rx", (1.7 + 0.5 * open).toFixed(2));
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [talking, mouth]);

  const bg = BACKGROUNDS[h % BACKGROUNDS.length]!;
  const skin = SKIN[(h >>> 3) % SKIN.length]!;
  const hair = HAIR[(h >>> 6) % HAIR.length]!;
  // 0 and 1 are short, 2 is long. A declared kind picks among its own.
  const style = kind === "male" ? (h >>> 9) % 2 : kind === "female" ? 2 : (h >>> 9) % 3;
  const glasses = (h >>> 12) % 4 === 0;
  const drawn = (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      aria-hidden
      className="shrink-0 rounded-full shadow-glow"
    >
      <clipPath id={`face-${h}`}>
        <circle cx="20" cy="20" r="20" />
      </clipPath>
      <g clipPath={`url(#face-${h})`}>
        <rect width="40" height="40" fill={bg} />
        {/* shoulders */}
        <path d="M6 40c1.5-7 7-10.5 14-10.5S32.5 33 34 40Z" fill="#fff" opacity="0.92" />
        {/* neck */}
        <rect x="17" y="24" width="6" height="7" rx="2.5" fill={skin} />
        {/* long hair sits behind the head */}
        {style === 2 && <path d="M10.5 18c0-6.5 4.2-10.5 9.5-10.5S29.5 11.5 29.5 18v10h-19Z" fill={hair} />}
        {/* head */}
        <ellipse cx="20" cy="18.5" rx="7.6" ry="8.6" fill={skin} />
        {/* hair on top */}
        {style === 0 && <path d="M12.3 17c-.4-5.6 3.2-9 7.7-9s8.3 3 7.8 9c-1.6-3-4.4-4.3-7.8-4.3S13.9 14 12.3 17Z" fill={hair} />}
        {style === 1 && <path d="M12.2 18c-.8-6.4 3.4-10.2 8.6-10 4.6.2 7.6 3.6 7 9.4-2.4-1.2-3.6-3.3-4.2-5-2.6 2.3-7 3.6-11.4 5.6Z" fill={hair} />}
        {style === 2 && <path d="M12.4 16.5c.4-5 3.6-8 7.6-8s7.4 3 7.6 8c-3.4-1.2-6.2-3.3-7.6-5.4-1.4 2.1-4.2 4.2-7.6 5.4Z" fill={hair} />}
        {/* eyes */}
        <circle cx="17.1" cy="19" r="0.95" fill="#1d1d24" />
        <circle cx="22.9" cy="19" r="0.95" fill="#1d1d24" />
        {glasses && (
          <g fill="none" stroke="#1d1d24" strokeWidth="0.7" opacity="0.85">
            <circle cx="17.1" cy="19" r="2.3" />
            <circle cx="22.9" cy="19" r="2.3" />
            <path d="M19.4 19h1.2" />
          </g>
        )}
        {talking ? (
          <ellipse ref={mouthShape} cx="20" cy="23.1" rx="1.7" ry="0.3" fill="#3a1d20" opacity="0.85" />
        ) : (
          // smile
          <path d="M17.6 22.6c1.4 1.3 3.4 1.3 4.8 0" fill="none" stroke="#1d1d24" strokeWidth="0.8" strokeLinecap="round" opacity="0.75" />
        )}
      </g>
    </svg>
  );
  if (!speaking) return drawn;
  return <span className="inline-grid shrink-0 rounded-full ring-2 ring-brand ring-offset-2 ring-offset-surface">{drawn}</span>;
}
