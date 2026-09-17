/**
 * The live stream — `GET /v1/interviews/{id}/events` (spec §7).
 *
 * **Not `EventSource`.** It cannot send headers, and every candidate-scoped
 * route needs the identity ones (FR-6.26) — with a real session it will need a
 * token. So this reads the same `text/event-stream` with `fetch`, which also
 * means `Last-Event-ID` can be sent on a reconnect and no event is missed.
 *
 * Two kinds of frame arrive. `interviewer.token` frames are a preview of a
 * line still being written; everything else is an event from the log, with its
 * `seq` as the id. The preview is replaced by the `question.asked` that
 * follows it, because that is the text of record — which is also what happens
 * when the guard swaps a model's line for its template mid-stream.
 */

import { useEffect, useRef, useState } from "react";

import { identityHeaders } from "./identity";
import type { StreamEvent } from "./types";

const RECONNECT_MS = 2000;

interface Handlers {
  onToken: (text: string) => void;
  onEvent: (event: StreamEvent) => void;
}

export function useInterviewStream(sessionId: string | undefined, handlers: Handlers) {
  const [connected, setConnected] = useState(false);
  const latest = useRef(handlers);
  latest.current = handlers;

  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    let lastSeq = 0;
    let stopped = false;
    let timer: number | undefined;

    async function read() {
      try {
        const response = await fetch(`/v1/interviews/${sessionId}/events`, {
          headers: {
            Accept: "text/event-stream",
            ...identityHeaders(),
            ...(lastSeq ? { "Last-Event-ID": String(lastSeq) } : {}),
          },
          signal: controller.signal,
        });
        if (!response.ok || !response.body) throw new Error(`stream ${response.status}`);
        setConnected(true);
        const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
        let buffer = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += value;
          // Frames are separated by a blank line; keep the tail.
          const frames = buffer.split("\n\n");
          buffer = frames.pop() ?? "";
          for (const frame of frames) dispatch(frame);
        }
      } catch {
        /* a dropped stream is normal — reconnect below */
      } finally {
        setConnected(false);
        if (!stopped) timer = window.setTimeout(read, RECONNECT_MS);
      }
    }

    function dispatch(frame: string) {
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith(":")) continue;
        const [field, ...rest] = line.split(": ");
        const value = rest.join(": ");
        if (field === "event") event = value;
        else if (field === "data") data += value;
        else if (field === "id") lastSeq = Number(value) || lastSeq;
      }
      if (!data) return;
      try {
        const parsed = JSON.parse(data);
        if (event === "interviewer.token") latest.current.onToken(String(parsed.token ?? ""));
        else if (event !== "stream.closed") latest.current.onEvent(parsed as StreamEvent);
      } catch {
        /* a half-written frame is not worth a crash */
      }
    }

    read();
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
      controller.abort();
    };
  }, [sessionId]);

  return { connected };
}
