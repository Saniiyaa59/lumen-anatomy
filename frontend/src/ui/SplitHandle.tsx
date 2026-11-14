import { useRef, type KeyboardEvent, type PointerEvent } from "react";

/** How far one press of an arrow key moves the border, in pixels. */
const KEY_STEP = 24;

interface SplitHandleProps {
  /** Current width of the column to the right of the handle, in pixels. */
  width: number;
  min: number;
  max: number;
  /** Called while dragging, with the width the column should take. Clamp it to min and max. */
  onResize: (width: number) => void;
  /** Called once when a drag or a key press finishes. */
  onDone: () => void;
  /** Called on a double-click, to go back to the default width. */
  onReset: () => void;
}

/**
 * The draggable border between the 3D view and the session column.
 *
 * Drag it, or focus it and use the arrow keys. Double-click resets it.
 */
export default function SplitHandle({ width, min, max, onResize, onDone, onReset }: SplitHandleProps) {
  const dragging = useRef(false);

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    dragging.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    // The column sits against the window's right edge, so its width is the distance from there.
    if (dragging.current) onResize(window.innerWidth - event.clientX);
  };
  const endDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return;
    dragging.current = false;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    onDone();
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.key === "ArrowLeft" ? KEY_STEP : event.key === "ArrowRight" ? -KEY_STEP : 0;
    if (step === 0) return;
    event.preventDefault();
    onResize(width + step);
    onDone();
  };

  return (
    <div
      className="split-handle"
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize the session column"
      aria-valuenow={Math.round(width)}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      title="Drag to resize. Double-click to reset."
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onDoubleClick={() => {
        onReset();
        onDone();
      }}
      onKeyDown={onKeyDown}
    />
  );
}
