/**
 * An interviewer's picture: their own photo (2026-10-09).
 *
 * From 2026-10-04 to 10-08 every interviewer was drawn here — an SVG face
 * from the persona's name, its mouth opening on each word. The user, after a
 * mock: "we don't want dummy faces in an interview, we want realistic human
 * faces". So the picture is now the portrait each interviewer's 3D head was
 * made from (`@ai/core`'s `InterviewerPhoto`, M11's
 * `/v1/voice/faces/{persona}.webp`): the same person on the setup page, the
 * plan, the transcript and in the room's tile. AI-generated, never a real
 * person's, and labelled so. Without a photo, initials — never a made-up face.
 *
 * The talking is the 3D head's (`TalkingHead`), so a small picture only
 * says who is speaking (the ring).
 */
import { InterviewerPhoto } from "@ai/core";

export function Face({
  persona,
  name,
  size = 36,
  speaking = false,
}: {
  /** M06's persona id. Without one, the initials. */
  persona?: string | null;
  name: string;
  size?: number;
  /** The interviewer's voice is saying this person's line right now. */
  speaking?: boolean;
}) {
  return <InterviewerPhoto persona={persona ?? ""} name={name} size={size} speaking={speaking} />;
}
