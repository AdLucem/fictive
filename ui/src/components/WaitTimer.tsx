import { useEffect, useState } from "react";
import type { WaitState } from "../types";
import { Clock } from "./icons";

/** `12s`, or `2:05` once a wait is a minute or longer. */
function formatDuration(seconds: number): string {
  const whole = Math.ceil(seconds);
  if (whole < 60) return `${whole}s`;
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

/**
 * The top bar's countdown for `wait` mode, with the clock symbol that shows
 * and hides it.
 *
 * The backend is asked nothing while this ticks. A turn is one synchronous
 * request, so the session only ever arrives with a fresh reading of how much
 * of the wait is left; this counts down from that reading locally and picks up
 * the next one when a turn returns. Hiding the countdown is a display choice,
 * so it lives here rather than in `App`: nothing else reads it.
 */
export function WaitTimer({ wait }: { wait: WaitState }) {
  const [visible, setVisible] = useState(true);
  const [remaining, setRemaining] = useState(wait.remaining);

  useEffect(() => {
    setRemaining(wait.remaining);
    if (!wait.active) return;

    // `session` is replaced wholesale on every response, so `wait` is a new
    // object each time -- the deps are its primitives, or this would restart
    // the interval on every render.
    const startedAt = Date.now();
    const id = window.setInterval(() => {
      // Recomputed from elapsed wall time rather than decremented, so a
      // throttled background tab resumes on the right number instead of
      // drifting by however many ticks it missed.
      const left = wait.remaining - (Date.now() - startedAt) / 1000;
      setRemaining(Math.max(0, left));
      // Nothing else will move this reading: the next one arrives with a
      // response, which re-runs the effect.
      if (left <= 0) window.clearInterval(id);
    }, 200);
    return () => window.clearInterval(id);
  }, [wait.active, wait.remaining, wait.total]);

  if (!wait.active) return null;

  const done = remaining <= 0;
  return (
    <>
      <button
        type="button"
        className="icon-button state-layer"
        aria-pressed={visible}
        aria-label={visible ? "Hide wait timer" : "Show wait timer"}
        title={visible ? "Hide wait timer" : "Show wait timer"}
        onClick={() => setVisible((open) => !open)}
      >
        <Clock />
      </button>
      {visible ? (
        <span
          className={`status ${done ? "status--wait-done" : "status--wait"}`}
          aria-live="off"
          title={`waiting ${formatDuration(wait.total)}`}
        >
          <span className="status__dot" />
          {done ? "wait over" : formatDuration(remaining)}
        </span>
      ) : null}
    </>
  );
}
