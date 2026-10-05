/**
 * The interviewer reads each line aloud, in the browser (2026-10-05) — the
 * interim output half of FR-6.10, as `speech.ts` is the input half.
 *
 * M11 owns voice. Until it exists, the browser's own speech synthesis speaks
 * each line of record in the voice the persona file names (`voice-core.ts`
 * chooses it), one sentence at a time. What M11 will do better, and this does
 * not try to: streaming the first clause before the line is finished, cutting
 * off within 350 ms when the student starts talking, and lip-sync from the
 * audio itself. This stops the moment the mic opens, which is the part of
 * barge-in a browser can do.
 *
 * New lines QUEUE behind the one being said — an acknowledgement and the next
 * question often arrive a moment apart, and the second must not cut the first
 * off mid-word. Only a repeat, a replay or a stop interrupts.
 *
 * The student can turn it off, and the choice is kept for this browser. A
 * screen-reader user hears the room's live region as well, so the off switch
 * is one press away rather than in a settings page.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { parseVoiceId, pickVoice, rateFor, speakable, splitSentences } from "./voice-core";

const PREFERENCE_KEY = "m06.voice";

function readPreference(): boolean {
  try {
    return localStorage.getItem(PREFERENCE_KEY) !== "off";
  } catch {
    return true;
  }
}

function writePreference(on: boolean) {
  try {
    localStorage.setItem(PREFERENCE_KEY, on ? "on" : "off");
  } catch {
    /* still applies for this visit */
  }
}

const synth: SpeechSynthesis | null =
  typeof window !== "undefined" && "speechSynthesis" in window ? window.speechSynthesis : null;

export const VOICE_SUPPORTED = synth !== null;

export function useInterviewerVoice(voiceId: string | null | undefined) {
  const [enabled, setEnabledState] = useState(readPreference);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>(() => synth?.getVoices() ?? []);
  /** Which line is being said — a turn id, or "idle" / "repeat". */
  const [speakingKey, setSpeakingKey] = useState<string | null>(null);
  /** The browser refused to speak before the student had clicked anything on
   *  this page (a reload mid-interview). One click says the line again. */
  const [blocked, setBlocked] = useState(false);
  const last = useRef<{ text: string; key: string } | null>(null);
  /** Bumped by every interruption; a stale utterance's events are ignored. */
  const generation = useRef(0);
  /** Utterances queued and not yet finished, across lines. */
  const outstanding = useRef(0);
  // When the latest word began, and whether this voice reports words at all;
  // the face reads these every frame (see `mouth`), so no React state changes
  // per word.
  const activity = useRef({ wordAt: 0, reportsWords: false });

  useEffect(() => {
    if (!synth) return;
    const load = () => setVoices(synth.getVoices());
    load();
    synth.addEventListener("voiceschanged", load);
    return () => synth.removeEventListener("voiceschanged", load);
  }, []);

  const spec = useMemo(() => parseVoiceId(voiceId), [voiceId]);
  const voice = useMemo(() => pickVoice(voices, spec), [voices, spec]);

  const stop = useCallback(() => {
    generation.current += 1;
    outstanding.current = 0;
    synth?.cancel();
    setSpeakingKey(null);
  }, []);

  const enqueue = useCallback(
    (text: string, key: string) => {
      if (!synth) return;
      const gen = generation.current;
      const chunks = splitSentences(speakable(text));
      chunks.forEach((chunk, index) => {
        const utterance = new SpeechSynthesisUtterance(chunk);
        if (voice) utterance.voice = voice;
        utterance.lang = voice?.lang ?? spec.locale;
        utterance.rate = rateFor(spec.manner);
        const finished = () => {
          if (gen !== generation.current) return;
          outstanding.current = Math.max(0, outstanding.current - 1);
          if (outstanding.current === 0) setSpeakingKey(null);
        };
        utterance.onstart = () => {
          if (gen !== generation.current) return;
          if (index === 0) activity.current = { wordAt: 0, reportsWords: false };
          setBlocked(false);
          setSpeakingKey(key);
        };
        utterance.onboundary = (event) => {
          if (gen !== generation.current || (event.name && event.name !== "word")) return;
          activity.current = { wordAt: performance.now(), reportsWords: true };
        };
        utterance.onend = finished;
        utterance.onerror = (event) => {
          if (gen !== generation.current) return;
          if (event.error === "not-allowed") setBlocked(true);
          finished();
        };
        outstanding.current += 1;
        synth.speak(utterance);
      });
    },
    [spec, voice],
  );

  /** Interrupt whatever is being said and say this instead. */
  const sayNow = useCallback(
    (text: string, key: string) => {
      stop();
      const gen = generation.current;
      // Chrome drops an utterance queued in the same tick as a cancel.
      window.setTimeout(() => {
        if (gen === generation.current) enqueue(text, key);
      }, 40);
    },
    [enqueue, stop],
  );

  /** A new line of the interview, said after anything still being said.
   *  Remembered even when the voice is off, so turning it on says it. */
  const speak = useCallback(
    (text: string, key: string) => {
      last.current = { text, key };
      if (enabled) enqueue(text, key);
    },
    [enabled, enqueue],
  );

  /** A line the student asked for again ("Repeat the question"). */
  const repeat = useCallback(
    (text: string, key: string) => {
      last.current = { text, key };
      if (enabled) sayNow(text, key);
    },
    [enabled, sayNow],
  );

  const replay = useCallback(() => {
    if (last.current) sayNow(last.current.text, last.current.key);
  }, [sayNow]);

  const setEnabled = useCallback(
    (on: boolean) => {
      setEnabledState(on);
      writePreference(on);
      if (!on) stop();
      // Turned on mid-question: say the question, which is what it is for.
      else if (last.current) sayNow(last.current.text, last.current.key);
    },
    [sayNow, stop],
  );

  // Leaving the room silences it — a tick later, and only if the room is
  // really gone. React's StrictMode runs this cleanup between its two mounts
  // in development, and cancelling at once dropped the opening question the
  // millisecond it was queued: on a first start the student heard nothing
  // until their first answer (found 2026-10-05, a speak/cancel trace).
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      window.setTimeout(() => {
        if (!mounted.current) synth?.cancel();
      }, 0);
    };
  }, []);

  /**
   * How open the mouth is, 0 to 1, for this frame. Opens on each word and
   * closes over ~220 ms; a voice that reports no word boundaries gets a
   * gentle loop instead, so the face still talks while it speaks.
   */
  const mouth = useCallback((now: number) => {
    const { wordAt, reportsWords } = activity.current;
    if (reportsWords) {
      const flutter = 0.65 + 0.35 * Math.abs(Math.sin(now / 85));
      return Math.max(0, 1 - (now - wordAt) / 220) * flutter;
    }
    return 0.25 + 0.4 * Math.abs(Math.sin(now / 120));
  }, []);

  return {
    supported: VOICE_SUPPORTED,
    enabled,
    setEnabled,
    speakingKey,
    blocked,
    speak,
    repeat,
    stop,
    replay,
    mouth,
    voiceName: voice?.name ?? null,
  };
}
