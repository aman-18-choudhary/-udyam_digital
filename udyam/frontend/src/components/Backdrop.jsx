import React, { Suspense, lazy, useEffect, useRef, useState } from "react";

const Scene = lazy(() => import("../three/Scene.jsx"));

function webglOk() {
  try {
    const c = document.createElement("canvas");
    return !!(window.WebGLRenderingContext && (c.getContext("webgl") || c.getContext("experimental-webgl")));
  } catch { return false; }
}

// Faint falling binary digits, echoing the case-study artwork. 2D canvas, a few columns, cheap.
function BinaryRain() {
  const ref = useRef(null);
  useEffect(() => {
    const cv = ref.current;
    if (!cv) return undefined;
    const ctx = cv.getContext("2d");
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0, cols = [], w = 0, h = 0;
    const fs = 15;
    const resize = () => {
      w = cv.width = window.innerWidth; h = cv.height = window.innerHeight;
      cols = Array.from({ length: Math.ceil(w / (fs * 2.2)) }, () => Math.random() * h);
    };
    resize();
    window.addEventListener("resize", resize);
    ctx.font = `${fs}px ui-monospace, Menlo, monospace`;
    let last = 0;
    const draw = (now) => {
      raf = requestAnimationFrame(draw);
      if (now - last < 70) return;
      last = now;
      ctx.fillStyle = "rgba(8,6,10,0.16)";
      ctx.fillRect(0, 0, w, h);
      cols.forEach((y, i) => {
        ctx.fillStyle = Math.random() > 0.93 ? "rgba(255,140,160,0.55)" : "rgba(255,50,85,0.22)";
        ctx.fillText(Math.random() > 0.5 ? "1" : "0", i * fs * 2.2, y);
        cols[i] = y > h + 20 || Math.random() > 0.985 ? 0 : y + fs;
      });
    };
    if (reduce) { ctx.fillStyle = "rgba(255,50,85,0.12)"; for (let i = 0; i < 90; i++) ctx.fillText(Math.random() > 0.5 ? "1" : "0", Math.random() * w, Math.random() * h); }
    else raf = requestAnimationFrame(draw);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", resize); };
  }, []);
  return <canvas ref={ref} className="rain" aria-hidden="true" />;
}

// Fixed full-screen background: CSS glow (always), binary rain, and the 3D globe when WebGL is available.
export default function Backdrop({ variant = "ambient" }) {
  const [gl, setGl] = useState(false);
  useEffect(() => { setGl(webglOk()); }, []);
  return (
    <div className={`backdrop backdrop-${variant}`} aria-hidden="true">
      <div className="glow glow-a" /><div className="glow glow-b" />
      <BinaryRain />
      {gl && <Suspense fallback={null}><Scene variant={variant} /></Suspense>}
      <div className="vignette" />
    </div>
  );
}
