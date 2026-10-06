/**
 * The spoken room's timing, captions and fallbacks — M11 days 11–12 in M06's
 * room. The rules live here; `InterviewStage` wires them in.
 *
 * - **When the interviewer answers** (FR-11.10). Never sooner than a person
 *   would: 300–900 ms after the student's last word, by the persona's own
 *   patience, and in Final Boss now and then a silence held on purpose.
 *   `@ai/core`'s `silenceBeforeMs` decides; this reads the persona's card.
 * - **What appears when** (spec §8). A fresh line's parts appear as their
 *   speaker starts saying them — a hand-over reads as two people, and a
 *   deliberate silence is felt rather than read through. With the voice off,
 *   blocked or stalled, the text shows at once: the line on screen is still
 *   the line of record.
 * - **"Okay" while the student talks** (FR-11.11). The asker's own word,
 *   softly, in a pause of an answer that has run a while, no more often than
 *   their warmth allows — and never in Final Boss.
 * - **Hold to talk** (FR-11.17). The open mic needs a steady connection and
 *   a clean echo path. On a poor network, after two drops, or when the room
 *   keeps hearing the interviewer's own voice, the student holds a button
 *   while they speak: one upload per answer, and the same interviewer.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import {
  serverAsrAvailable,
  silenceBeforeMs,
  speakOnServer,
  transcribeOnServer,
  useListening,
  useRollingCaption,
  type AsrResult,
  type Caption,
  type InterviewerVoice,
} from "@ai/core";

import type { PersonaCard, TurnView } from "./types";

/** The ledger's clock (`@ai/core`'s): epoch milliseconds. */
export function nowMs(): number {
  return Math.round(performance.timeOrigin + performance.now());
}

// ── when the interviewer answers ──────────────────────────────────────────

/** FR-11.10: the earliest the interviewer's first sound may come after the
 *  student's last word. Zero when nothing was just answered. */
export function notBeforeFor(
  answeredAt: number | null,
  line: TurnView,
  card: PersonaCard | undefined,
  mode: string,
): number {
  if (answeredAt === null) return 0;
  const newQuestion =
    line.probe_move === null && line.question_source !== null && line.question_source !== "closing";
  return (
    answeredAt +
    silenceBeforeMs({ patience: card?.patience ?? 0.5, mode, key: line.turn_id, newQuestion })
  );
}

// ── what appears when ─────────────────────────────────────────────────────

export interface Reveal {
  /** Whether a part of a line (its "turn:index" id) may be shown yet. */
  shown: (partId: string) => boolean;
  /** A line is waiting on its voice past the silence meant for it — the
   *  room shows that it is thinking (spec §8: a stall, not a silence). */
  overdue: boolean;
  /** Hold these parts, in speaking order, until the voice reaches them. */
  hold: (partIds: string[], notBefore: number) => void;
  /** Changes whenever what is shown does, for the room's scroll. */
  version: number;
}

/** Nothing reached this long after a line may start: show it anyway. */
const REVEAL_ANYWAY_MS = 8_000;
/** Whatever happens, a held line is on screen within this. */
const REVEAL_AT_MOST_MS = 45_000;

export function useReveal(voice: InterviewerVoice, active: boolean): Reveal {
  const [held, setHeld] = useState<string[]>([]);
  const [overdue, setOverdue] = useState(false);
  const [version, setVersion] = useState(0);
  const waiting = useRef<number[]>([]); // timers until the voice starts
  const caps = useRef<number[]>([]);
  const spoke = useRef(false);

  const clear = (timers: { current: number[] }) => {
    for (const t of timers.current) window.clearTimeout(t);
    timers.current = [];
  };
  const release = useCallback(() => {
    clear(waiting);
    clear(caps);
    setHeld((current) => (current.length ? [] : current));
    setOverdue(false);
    setVersion((v) => v + 1);
  }, []);

  // The voice reached a part: it and everything before it are shown.
  useEffect(() => {
    const at = voice.speakingPart;
    if (!at) return;
    setHeld((current) => {
      const i = current.indexOf(at);
      return i < 0 ? current : current.slice(i + 1);
    });
    clear(waiting);
    setOverdue(false);
    setVersion((v) => v + 1);
  }, [voice.speakingPart]);

  // The voice finished, or was stopped: whatever it did not reach is shown —
  // a barge-in's unheard words included, dimmed by the line itself.
  useEffect(() => {
    if (voice.speakingKey !== null) {
      spoke.current = true;
      return;
    }
    if (spoke.current) {
      spoke.current = false;
      release();
    }
  }, [voice.speakingKey, release]);

  useEffect(() => {
    if (!active) release();
  }, [active, release]);
  useEffect(
    () => () => {
      clear(waiting);
      clear(caps);
    },
    [],
  );

  const hold = useCallback(
    (partIds: string[], notBefore: number) => {
      if (!active || partIds.length === 0) return;
      setHeld((current) => [...current, ...partIds]);
      const from = Math.max(0, notBefore - nowMs());
      // Already past its silence: overdue in this same commit, so the room's
      // dots carry straight on from the wait for the line itself.
      if (from === 0) setOverdue(true);
      else waiting.current.push(window.setTimeout(() => setOverdue(true), from));
      waiting.current.push(window.setTimeout(release, from + REVEAL_ANYWAY_MS));
      caps.current.push(window.setTimeout(release, from + REVEAL_AT_MOST_MS));
    },
    [active, release],
  );

  const shown = useCallback((partId: string) => !held.includes(partId), [held]);
  return { shown, overdue: overdue && held.length > 0, hold, version };
}

// ── "okay" while the student talks ────────────────────────────────────────

/** An answer this long before the first: earlier reads as a cue to stop. */
const BACKCHANNEL_AFTER_MS = 5_000;

/** FR-11.11: the room's `onPause` — the asker says one of their own words,
 *  softly, when the student has been talking a while. */
export function useBackchannels(options: {
  enabled: boolean;
  voice: InterviewerVoice;
  asker: () => PersonaCard | undefined;
}): (pause: { at: number; talkingMs: number }) => void {
  const latest = useRef(options);
  latest.current = options;
  const last = useRef(0);
  const said = useRef(0);
  return useCallback((pause) => {
    const { enabled, voice, asker } = latest.current;
    const card = asker();
    const words = card?.backchannels ?? [];
    if (!enabled || !card || words.length === 0) return;
    if (pause.talkingMs < BACKCHANNEL_AFTER_MS) return;
    if (pause.at - last.current < (card.backchannel_every_s ?? 10) * 1000) return;
    last.current = pause.at;
    const word = words[said.current++ % words.length]!;
    voice.backchannel(word, { personaId: card.id, voiceId: card.voice_id });
  }, []);
}

/** Each panelist's words made once, before they are needed: a backchannel
 *  that is not instant is dropped (`@ai/core`), and M11 keeps what it makes. */
export function useWarmBackchannels(enabled: boolean, cards: PersonaCard[]): void {
  const done = useRef(new Set<string>());
  const key = cards.map((card) => card.id).join(",");
  useEffect(() => {
    if (!enabled) return;
    // Their "okay"s, and the "go ahead" said as they yield (EC-11.1).
    const todo = cards
      .flatMap((card) =>
        [...(card.backchannels ?? []), ...(card.go_ahead ? [card.go_ahead] : [])].map((word) => ({
          card,
          word,
        })),
      )
      .filter(({ card, word }) => !done.current.has(`${card.id}:${word}`));
    if (todo.length === 0) return;
    let stopped = false;
    void (async () => {
      for (const { card, word } of todo) {
        if (stopped) return;
        try {
          const clip = await speakOnServer(word, { personaId: card.id, voiceId: card.voice_id });
          URL.revokeObjectURL(clip.url);
          done.current.add(`${card.id}:${word}`);
        } catch {
          return; // the voice is not there; backchannels will not be either
        }
      }
    })();
    return () => {
      stopped = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, key]);
}

// ── the connection ────────────────────────────────────────────────────────

interface NetworkInformation extends EventTarget {
  effectiveType?: string;
  downlink?: number;
  rtt?: number;
  saveData?: boolean;
}

function connection(): NetworkInformation | undefined {
  return (navigator as Navigator & { connection?: NetworkInformation }).connection;
}

/** FR-11.17, spec §6.9: too poor for the open mic — 2G, under ~150 kbps, a
 *  round trip over 1.5 s, or the student asked to save data. Browsers that
 *  cannot say are taken at their word: not poor. */
export function poorConnection(): boolean {
  const c = connection();
  if (!c) return false;
  if (c.saveData) return true;
  if (c.effectiveType === "slow-2g" || c.effectiveType === "2g") return true;
  if (typeof c.downlink === "number" && c.downlink > 0 && c.downlink < 0.15) return true;
  return typeof c.rtt === "number" && c.rtt > 1500;
}

/** `poorConnection()`, kept current as the connection changes. */
export function usePoorConnection(): boolean {
  const [poor, setPoor] = useState(poorConnection);
  useEffect(() => {
    const c = connection();
    if (!c) return;
    const check = () => setPoor(poorConnection());
    c.addEventListener("change", check);
    return () => c.removeEventListener("change", check);
  }, []);
  return poor;
}

// ── hold to talk ──────────────────────────────────────────────────────────

/** One answer, said while the button was held. Times on the ledger's clock. */
export interface HeldTurn {
  startedAt: number;
  endedAt: number;
  /** M11's words; null when the recogniser could not answer. */
  text: string | null;
  asr: AsrResult | null;
  audio: Blob | null;
}

export interface PushToTalk {
  /** The microphone is open (it stays open, so the first word is caught). */
  active: boolean;
  error: string | null;
  held: boolean;
  /** The answer is on its way and being written down. */
  sending: boolean;
  level: () => number;
  press: () => void;
  release: () => void;
  /** EC-11.12: the device took the microphone (a call). */
  interrupted: boolean;
  /** EC-11.7: the microphone in use. */
  device: { label: string; sampleRate: number | null } | null;
  /** FR-11.3: the answer so far, from M11's recogniser, while held. */
  caption: Caption | null;
}

/** Shorter than this is a tap, not an answer. */
const SHORTEST_HOLD_MS = 350;
/** A little either side of the hold: a word started as the button went down,
 *  and the last syllable still in the audio thread when it came up. */
const LEAD_MS = 250;
const TAIL_MS = 200;

export function usePushToTalk(options: {
  enabled: boolean;
  /** The question being answered: the recogniser's prompt. */
  context: () => string | null | undefined;
  /** The button went down — the interviewer's cue to stop. */
  onPress: (at: number) => void;
  onTurn: (turn: HeldTurn) => void;
  /** FR-11.3: caption the answer from M11's recogniser while it is held —
   *  for a browser that cannot caption it itself. */
  caption?: boolean;
}): PushToTalk {
  const latest = useRef(options);
  latest.current = options;
  const listening = useListening({ enabled: options.enabled, keepAudio: true });
  const pressedAt = useRef<number | null>(null);
  const [held, setHeld] = useState(false);
  const [sending, setSending] = useState(0);
  const recogniser = useRef(false);
  useEffect(() => {
    if (options.enabled) void serverAsrAvailable().then((ready) => (recogniser.current = ready));
  }, [options.enabled]);

  const press = useCallback(() => {
    if (pressedAt.current !== null || !latest.current.enabled) return;
    pressedAt.current = nowMs();
    setHeld(true);
    latest.current.onPress(pressedAt.current);
  }, []);

  const release = useCallback(() => {
    const from = pressedAt.current;
    pressedAt.current = null;
    setHeld(false);
    if (from === null) return;
    const to = nowMs();
    if (to - from < SHORTEST_HOLD_MS) return;
    window.setTimeout(() => {
      const audio = listening.audioBetween(from - LEAD_MS, to + TAIL_MS);
      const base = { startedAt: from, endedAt: to };
      if (!audio || !recogniser.current) {
        latest.current.onTurn({ ...base, text: null, asr: null, audio });
        return;
      }
      setSending((n) => n + 1);
      transcribeOnServer(audio, latest.current.context())
        .then((asr) => latest.current.onTurn({ ...base, text: asr.text.trim(), asr, audio }))
        .catch(() => latest.current.onTurn({ ...base, text: null, asr: null, audio }))
        .finally(() => setSending((n) => Math.max(0, n - 1)));
    }, TAIL_MS);
    // `listening` is read through its own refs; a new object each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listening.audioBetween]);

  const caption = useRollingCaption({
    enabled: options.enabled && Boolean(options.caption),
    from: () => pressedAt.current,
    audioBetween: (from, to) => listening.audioBetween(from, to),
    context: () => latest.current.context(),
  });

  return {
    active: listening.active,
    error: listening.error,
    held,
    sending: sending > 0,
    level: listening.level,
    press,
    release,
    interrupted: listening.interrupted,
    device: listening.device,
    caption,
  };
}
