/**
 * What a student can be practising FOR, offered by whoever hosts this module.
 *
 * The setup screen could only be pointed at a job description or a drive by a
 * URL parameter, so a student who opened "Mock interview" from the menu could
 * not choose one. M06 does not know a student's targets — M04 keeps the drives
 * they told the platform about, M02 the postings they pasted — and a module
 * reaching into two others' APIs from its own screen is how frontends couple.
 * So the host provides them, the way M15 publishes its rail through the
 * shell's context: Platform_Shell fills this from the student's profile, and
 * standalone there is no provider and the picker offers "general" and links.
 */
import { createContext } from "react";

export interface MockTarget {
  /** Stable key, also how the picker knows which one the URL already names. */
  key: string;
  label: string;
  /** "Drive in 12 days", "Job description". */
  sub?: string;
  /** The `/mock` query that plans for this target. */
  params: Record<string, string>;
}

export const MockTargetsContext = createContext<MockTarget[]>([]);
