/**
 * The student's own picture, offered by whoever hosts this module (2026-11-17).
 *
 * Shown on their tile in the room when the camera is off, in place of the
 * "You" circle. M06 does not hold a student's picture — M04 does, set from
 * the platform's Settings — so, like `MockTargetsContext`, the host provides
 * it: Platform_Shell fills this with the picture's URL, and standalone there
 * is no provider and the tile keeps its circle.
 */
import { createContext } from "react";

export const SelfPhotoContext = createContext<string | null>(null);
