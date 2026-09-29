/** The app bar's view picker: the main chat, or one actor's full history. */

import { useEffect, useRef, useState } from "react";
import type { ActorHistory } from "../types";
import { Chevron, Stack } from "./icons";

interface Props {
  histories: ActorHistory[];
  mainActor: string;
  /** The actor whose history is on screen, or `null` for the main chat. */
  current: string | null;
  onPick: (actor: string | null) => void;
}

export function ActorMenu({ histories, mainActor, current, onPick }: Props) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  // Any click outside, or escape, puts the menu away without changing the view.
  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const pick = (actor: string | null) => {
    onPick(actor);
    setOpen(false);
  };

  return (
    <div className="actor-menu" ref={root}>
      <button
        type="button"
        className="button-outlined actor-menu__trigger state-layer"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-pressed={current !== null}
        onClick={() => setOpen((value) => !value)}
      >
        <Stack size={18} />
        <span className="actor-menu__label">{current ?? "Main"}</span>
        <Chevron className="actor-menu__chevron" />
      </button>

      {open ? (
        <div className="actor-menu__list" role="menu" aria-label="Show a history">
          <button
            type="button"
            role="menuitemradio"
            aria-checked={current === null}
            className="actor-menu__item state-layer"
            onClick={() => pick(null)}
          >
            <span className="actor-menu__name">Main</span>
            <span className="actor-menu__meta">chat</span>
          </button>
          <div className="actor-menu__divider" role="separator" />
          {histories.map((history) => (
            <button
              type="button"
              role="menuitemradio"
              key={history.name}
              aria-checked={current === history.name}
              className="actor-menu__item state-layer"
              onClick={() => pick(history.name)}
            >
              <span className="actor-menu__name">{history.name}</span>
              <span className="actor-menu__meta">
                {history.name === mainActor ? "main · " : ""}
                {history.messages.length} msg{history.messages.length === 1 ? "" : "s"}
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
