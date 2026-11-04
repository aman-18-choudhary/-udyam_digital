import { useEffect } from "react";

// One delegated pointer listener gives every `.tilt` element a subtle 3D tilt and a moving glare.
export default function useTilt() {
  useEffect(() => {
    const fine = window.matchMedia("(pointer: fine)").matches;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!fine || reduce) return undefined;
    let el = null;
    const reset = (n) => { if (n) { n.style.setProperty("--rx", "0deg"); n.style.setProperty("--ry", "0deg"); n.classList.remove("tilting"); } };
    const move = (e) => {
      const t = e.target.closest?.(".tilt");
      if (t !== el) { reset(el); el = t || null; }
      if (!t) return;
      const r = t.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      const max = Math.min(5, 1800 / Math.max(r.width, 300));
      t.style.setProperty("--ry", `${((x - 0.5) * 2 * max).toFixed(2)}deg`);
      t.style.setProperty("--rx", `${((0.5 - y) * 2 * max).toFixed(2)}deg`);
      t.style.setProperty("--mx", `${(x * 100).toFixed(1)}%`);
      t.style.setProperty("--my", `${(y * 100).toFixed(1)}%`);
      t.classList.add("tilting");
    };
    const leave = () => { reset(el); el = null; };
    document.addEventListener("pointermove", move, { passive: true });
    document.addEventListener("pointerleave", leave);
    return () => { document.removeEventListener("pointermove", move); document.removeEventListener("pointerleave", leave); };
  }, []);
}
