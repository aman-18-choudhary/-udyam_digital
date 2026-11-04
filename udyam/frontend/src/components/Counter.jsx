import React, { useEffect, useRef, useState } from "react";
import { inr } from "../api.js";

// Rolls a rupee amount up (or down) to its new value, so a price change is noticed, not just replaced.
export default function Counter({ value, ms = 650 }) {
  const [shown, setShown] = useState(value ?? 0);
  const from = useRef(value ?? 0);
  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const start = from.current, end = value ?? 0;
    if (reduce || start === end) { setShown(end); from.current = end; return undefined; }
    let raf = 0;
    const t0 = performance.now();
    const step = (now) => {
      const k = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - k, 3);
      setShown(start + (end - start) * e);
      if (k < 1) raf = requestAnimationFrame(step); else from.current = end;
    };
    raf = requestAnimationFrame(step);
    return () => { cancelAnimationFrame(raf); from.current = end; };
  }, [value, ms]);
  return <>{inr(shown)}</>;
}
