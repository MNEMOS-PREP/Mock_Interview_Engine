/**
 * Speaking an answer, in the browser (2026-10-04) — the interim half of 5.3.
 *
 * Placement interviews are spoken, and typing three paragraphs trains the
 * wrong skill. The voice engine (M11) is not built, so this uses the browser's
 * own speech recognition (the Web Speech API: Chrome, Edge, Safari) to put
 * words into the SAME answer box, where the student reads and edits them
 * before anything is sent. Nothing about the backend changes: what M13 marks
 * is still the text the student chose to submit.
 *
 * Honest about its limits: where the browser has no recognition the mic is
 * simply not offered, and the filler-word count is a count of words in the
 * transcript, said as a count — not a judgement of fluency, which is M12's.
 */
import { useCallback, useEffect, useRef, useState } from "react";

interface RecognitionResult {
  readonly isFinal: boolean;
  readonly 0: { readonly transcript: string };
}

interface RecognitionEvent {
  readonly resultIndex: number;
  readonly results: ArrayLike<RecognitionResult>;
}

interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  onresult: ((event: RecognitionEvent) => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error: string }) => void) | null;
}

type RecognitionCtor = new () => Recognition;

function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export const SPEECH_SUPPORTED = recognitionCtor() !== null;

export const RECOGNITION_LANG = "en-IN";

/** The words people reach for while thinking. Counted, never removed. */
const FILLERS = ["um", "umm", "uh", "uhh", "er", "erm", "like", "basically", "actually", "you know"];

export function fillerCount(text: string): { total: number; top: string[] } {
  const lower = ` ${text.toLowerCase().replace(/[^a-z\s']/g, " ")} `;
  const counts = new Map<string, number>();
  for (const word of FILLERS) {
    const n = lower.split(` ${word} `).length - 1;
    if (n > 0) counts.set(word, n);
  }
  const total = [...counts.values()].reduce((a, b) => a + b, 0);
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([w]) => w);
  return { total, top };
}

/**
 * Dictation into a draft. `onText` receives each finished phrase; `interim`
 * is what is being heard right now, for showing under the box.
 */
export function useDictation(onText: (text: string) => void) {
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const recognition = useRef<Recognition | null>(null);
  const handler = useRef(onText);
  handler.current = onText;

  const stop = useCallback(() => {
    recognition.current?.stop();
  }, []);

  const start = useCallback(() => {
    const Ctor = recognitionCtor();
    if (!Ctor) return;
    const r = new Ctor();
    // Indian English, whatever the laptop reports: most report en-US even in
    // India, and en-US recognition mishears Indian-accented English more. The
    // interview is in English, so a Hindi or Tamil locale is not used either.
    r.lang = RECOGNITION_LANG;
    r.continuous = true;
    r.interimResults = true;
    r.onresult = (event) => {
      let heard = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i]!;
        if (result.isFinal) handler.current(result[0].transcript.trim());
        else heard += result[0].transcript;
      }
      setInterim(heard);
    };
    r.onerror = (event) => {
      setError(
        event.error === "not-allowed"
          ? "The browser blocked the microphone. Allow it in the address bar and try again."
          : "The microphone stopped. You can keep typing, or try again.",
      );
    };
    r.onend = () => {
      setListening(false);
      setInterim("");
      recognition.current = null;
    };
    recognition.current = r;
    setError(null);
    setListening(true);
    r.start();
  }, []);

  useEffect(() => () => recognition.current?.stop(), []);

  return { supported: SPEECH_SUPPORTED, listening, interim, error, start, stop };
}
