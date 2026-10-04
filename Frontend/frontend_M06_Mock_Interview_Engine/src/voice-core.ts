/**
 * The interviewer's voice, worked out from what the browser has (2026-10-05).
 *
 * Pure functions — no React, no `window` — so `npm test` runs them in Node.
 * `voice.ts` is the hook that uses them.
 *
 * ── Why the browser, and why it is enough for now ───────────────────────────
 * M11 (the voice engine) is not built. Every browser ships speech synthesis,
 * and Microsoft Edge's includes neural Indian-English voices ("Microsoft
 * Neerja / Prabhat Online (Natural) - English (India)") at no cost and with
 * nothing installed. Chrome on Windows has Windows' own Indian-English voices
 * (Heera, Ravi), and Safari on a Mac has Veena and Rishi. So each persona's
 * authored `voice_id` (`en-IN-female-warm`) can be honoured today, and M11
 * maps the same id to its own voices later.
 */

export interface VoiceLike {
  readonly name: string;
  readonly lang: string;
  readonly localService: boolean;
}

/** A persona's `voice_id`, read: `locale-kind-manner`. */
export interface VoiceSpec {
  locale: string;
  /** The persona file's word ("female", "male") — authored, never inferred. */
  kind: string;
  /** "warm", "neutral", "brisk", "measured", "casual". */
  manner: string;
}

const DEFAULT_SPEC: VoiceSpec = { locale: "en-IN", kind: "", manner: "neutral" };

export function parseVoiceId(id: string | null | undefined): VoiceSpec {
  const match = /^([a-z]{2})-([A-Z]{2})-([a-z]+)-([a-z]+)$/.exec(id ?? "");
  if (!match) return DEFAULT_SPEC;
  return { locale: `${match[1]}-${match[2]}`, kind: match[3]!, manner: match[4]! };
}

/**
 * Voice names browsers ship whose kind is known.
 *
 * The Web Speech API does not say whether a voice is a woman's or a man's, so
 * this is the one table in the module — the fallback the no-hardcoding rule
 * allows when nothing can be derived. A voice not in it is still used, chosen
 * by locale and quality; it is only not matched on kind. Names a browser puts
 * in the voice itself ("Google UK English Female") are read from the name.
 */
const KNOWN_KIND: Record<string, "female" | "male"> = {
  // Indian English — Edge online, Windows, Azure names Edge sometimes lists, macOS
  neerja: "female", prabhat: "male", heera: "female", ravi: "male",
  aashi: "female", ananya: "female", kavya: "female", aarav: "male", kunal: "male", rehaan: "male",
  veena: "female", rishi: "male",
  // US English — Windows and Edge online
  zira: "female", david: "male", mark: "male", aria: "female", jenny: "female", guy: "male",
  ana: "female", michelle: "female", emma: "female", ava: "female",
  christopher: "male", eric: "male", roger: "male", steffan: "male", andrew: "male", brian: "male",
  // UK English — Windows and Edge online
  hazel: "female", susan: "female", george: "male", libby: "female", maisie: "female", sonia: "female",
  ryan: "male", thomas: "male",
  // macOS
  samantha: "female", karen: "female", moira: "female", tessa: "female", daniel: "male", alex: "male",
};

export function kindOf(voice: VoiceLike): "female" | "male" | null {
  if (/\bfemale\b/i.test(voice.name)) return "female";
  if (/\bmale\b/i.test(voice.name)) return "male";
  for (const word of voice.name.toLowerCase().split(/[^a-z]+/)) {
    const known = KNOWN_KIND[word];
    if (known) return known;
  }
  return null;
}

/**
 * How well a voice fits a persona. An exact locale beats the same language;
 * a neural voice beats a robotic one; the persona's kind matters more than
 * its accent — Priya in a British woman's voice reads as Priya, in an Indian
 * man's voice she does not. Another language entirely is not a candidate.
 */
export function score(voice: VoiceLike, spec: VoiceSpec): number {
  const lang = voice.lang.replace("_", "-").toLowerCase();
  const want = spec.locale.toLowerCase();
  let points: number;
  if (lang === want) points = 100;
  else if (lang.slice(0, 2) === want.slice(0, 2)) points = 40;
  else return Number.NEGATIVE_INFINITY;
  if (/\b(natural|neural)\b/i.test(voice.name)) points += 30;
  else if (/\b(online|google)\b/i.test(voice.name) || !voice.localService) points += 15;
  const kind = kindOf(voice);
  if (kind && spec.kind) points += kind === spec.kind ? 40 : -40;
  return points;
}

/** The best voice for a persona, or null when the browser has no voice in
 *  its language. Ties go by name, so the choice is the same on every load. */
export function pickVoice<V extends VoiceLike>(voices: readonly V[], spec: VoiceSpec): V | null {
  let best: V | null = null;
  let bestScore = Number.NEGATIVE_INFINITY;
  for (const voice of voices) {
    const s = score(voice, spec);
    if (s > bestScore || (s === bestScore && best && voice.name < best.name)) {
      best = voice;
      bestScore = s;
    }
  }
  return bestScore === Number.NEGATIVE_INFINITY ? null : best;
}

/** The persona's manner as a speaking rate. Pitch is left alone: neural
 *  voices bend badly, and pace is what an interviewer's manner sounds like. */
const RATE: Record<string, number> = { warm: 0.97, neutral: 1, brisk: 1.1, measured: 0.92, casual: 1.04 };

export function rateFor(manner: string): number {
  return RATE[manner] ?? 1;
}

/** Things a voice would read wrongly, said the way an interviewer says them.
 *  M11's lexicon (EC-11.11) will own this; these are the ones that come up. */
const SAY: [RegExp, string][] = [
  [/\bC\+\+/g, "C plus plus"],
  [/\bC#/g, "C sharp"],
  [/\.NET\b/g, "dot net"],
  [/\be\.g\./gi, "for example"],
  [/\bi\.e\./gi, "that is"],
  [/\betc\./gi, "etcetera"],
  [/\bvs\.?(?=\s)/gi, "versus"],
  [/&/g, " and "],
];

/** A line as it should be heard: code and links are on screen, not read out. */
export function speakable(text: string): string {
  let out = text
    .replace(/```[\s\S]*?(```|$)/g, " The code is on your screen. ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/https?:\/\/\S+/g, " the link on your screen ")
    // Big-O as it is said: O(n log n) → "O of n log n", O(n^2) → "O of n squared".
    .replace(/\bO\(([^()]{1,24})\)/g, (_, inner: string) =>
      `O of ${inner.replace(/\^\s*2\b/g, " squared").replace(/\^\s*3\b/g, " cubed")}`,
    )
    .replace(/\n\s*[-•*]\s+/g, ". ");
  for (const [pattern, said] of SAY) out = out.replace(pattern, said);
  return out
    .replace(/[*_#>|]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Sentences, each short enough to speak whole. Chrome stops a long utterance
 * partway with no error, and one sentence at a time also lets the student cut
 * in between them rather than after a paragraph.
 */
export function splitSentences(text: string, max = 220): string[] {
  const out: string[] = [];
  for (const sentence of text.split(/(?<=[.?!])\s+/)) {
    let rest = sentence.trim();
    while (rest.length > max) {
      const cut = Math.max(rest.lastIndexOf(", ", max), rest.lastIndexOf(" ", max));
      const at = cut > max / 3 ? cut + 1 : max;
      out.push(rest.slice(0, at).trim());
      rest = rest.slice(at).trim();
    }
    if (rest) out.push(rest);
  }
  return out;
}
