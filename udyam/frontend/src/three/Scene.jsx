// A glowing dotted globe with animated data arcs between Indian cities and a few global hubs.
// Loaded lazily (see Backdrop.jsx) so the first paint never waits for three.js.
import React, { useEffect, useRef } from "react";
import * as THREE from "three";

const R = 1;
const RED = new THREE.Color("#ff1f45");
const HOT = new THREE.Color("#ff8aa0");
const WHITE = new THREE.Color("#ffffff");

// [lat, lon]
const INDIA = {
  Delhi: [28.6, 77.2], Mumbai: [19.1, 72.9], Bengaluru: [12.97, 77.6], Chennai: [13.1, 80.3], Kolkata: [22.6, 88.4],
  Hyderabad: [17.4, 78.5], Pune: [18.5, 73.9], Ahmedabad: [23.0, 72.6], Jaipur: [26.9, 75.8], Nagpur: [21.1, 79.1],
  Kochi: [9.9, 76.3], Lucknow: [26.8, 80.9],
};
const WORLD = { Singapore: [1.35, 103.8], Dubai: [25.2, 55.3], London: [51.5, -0.1], "New York": [40.7, -74], Tokyo: [35.7, 139.7] };

function toVec(lat, lon, r = R) {
  const phi = (lat * Math.PI) / 180, lam = (lon * Math.PI) / 180;
  return new THREE.Vector3(r * Math.cos(phi) * Math.sin(lam), r * Math.sin(phi), r * Math.cos(phi) * Math.cos(lam));
}

function arc(a, b, lift = 0.28) {
  const mid = a.clone().add(b).multiplyScalar(0.5).normalize().multiplyScalar(R + lift * a.distanceTo(b));
  return new THREE.QuadraticBezierCurve3(a, mid, b);
}

const dotVert = `
  attribute float aSize; attribute float aSeed; attribute vec3 aColor;
  uniform float uTime; uniform float uPx;
  varying vec3 vColor; varying float vAlpha;
  void main() {
    vColor = aColor;
    float tw = 0.65 + 0.35 * sin(uTime * 1.6 + aSeed * 40.0);
    vAlpha = tw;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = aSize * uPx * (4.2 / -mv.z) * (0.8 + 0.4 * tw);
    gl_Position = projectionMatrix * mv;
  }`;
const dotFrag = `
  varying vec3 vColor; varying float vAlpha;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    float a = smoothstep(0.5, 0.0, d) * vAlpha;
    gl_FragColor = vec4(vColor * 1.6, a * 1.25);
  }`;
const rimVert = `
  varying vec3 vN; varying vec3 vV;
  void main() {
    vN = normalize(normalMatrix * normal);
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vV = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }`;
const rimFrag = `
  varying vec3 vN; varying vec3 vV; uniform vec3 uColor; uniform float uPower; uniform float uGain;
  void main() {
    float f = pow(1.0 - max(dot(vN, vV), 0.0), uPower);
    gl_FragColor = vec4(uColor, f * uGain);
  }`;

export default function Scene({ variant = "ambient" }) {
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const hero = variant === "hero";
    const small = window.innerWidth < 720;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: !small, powerPreference: "low-power" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, small ? 1.25 : 1.6));
    renderer.setClearColor(0x000000, 0);
    el.appendChild(renderer.domElement);
    renderer.domElement.style.cssText = "width:100%;height:100%;display:block";

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 50);
    camera.position.set(0, 0, 4.2);

    const globe = new THREE.Group();
    scene.add(globe);

    // dotted sphere (Fibonacci lattice), brighter and larger near India
    const N = small ? 1400 : 2600;
    const pos = new Float32Array(N * 3), col = new Float32Array(N * 3), size = new Float32Array(N), seed = new Float32Array(N);
    const focus = toVec(21, 79).normalize();
    for (let i = 0; i < N; i++) {
      const y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = Math.PI * (3 - Math.sqrt(5)) * i;
      const v = new THREE.Vector3(Math.cos(th) * r, y, Math.sin(th) * r);
      pos.set([v.x * R, v.y * R, v.z * R], i * 3);
      const near = Math.max(0, v.dot(focus));
      const c = RED.clone().lerp(HOT, near * 0.6).lerp(WHITE, Math.pow(near, 8) * 0.5);
      col.set([c.r, c.g, c.b], i * 3);
      size[i] = 2.4 + near * 2.4 + Math.random() * 1.1;
      seed[i] = Math.random();
    }
    const dg = new THREE.BufferGeometry();
    dg.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    dg.setAttribute("aColor", new THREE.BufferAttribute(col, 3));
    dg.setAttribute("aSize", new THREE.BufferAttribute(size, 1));
    dg.setAttribute("aSeed", new THREE.BufferAttribute(seed, 1));
    const dotMat = new THREE.ShaderMaterial({
      vertexShader: dotVert, fragmentShader: dotFrag, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uTime: { value: 0 }, uPx: { value: renderer.getPixelRatio() } },
    });
    globe.add(new THREE.Points(dg, dotMat));

    // dark core so dots on the far side fade behind it, plus a red rim light
    globe.add(new THREE.Mesh(new THREE.SphereGeometry(R * 0.985, 48, 48), new THREE.MeshBasicMaterial({ color: 0x16040b })));
    const rim = (scale, power, gain) => new THREE.Mesh(
      new THREE.SphereGeometry(R * scale, 48, 48),
      new THREE.ShaderMaterial({
        vertexShader: rimVert, fragmentShader: rimFrag, transparent: true, depthWrite: false, side: THREE.BackSide,
        blending: THREE.AdditiveBlending, uniforms: { uColor: { value: RED }, uPower: { value: power }, uGain: { value: gain } },
      }));
    scene.add(rim(1.12, 3.4, 0.75));
    const inner = rim(1.0, 2.6, 0.42);
    inner.material.side = THREE.FrontSide;
    globe.add(inner);

    // latitude and longitude lines give the sphere its volume
    const gratMat = new THREE.LineBasicMaterial({ color: 0xff4d6d, transparent: true, opacity: 0.10, depthWrite: false, blending: THREE.AdditiveBlending });
    for (let lat = -60; lat <= 60; lat += 20) {
      const pts = [];
      for (let lon = 0; lon <= 360; lon += 6) pts.push(toVec(lat, lon, R * 1.001));
      globe.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), gratMat));
    }
    for (let lon = 0; lon < 360; lon += 20) {
      const pts = [];
      for (let lat = -88; lat <= 88; lat += 6) pts.push(toVec(lat, lon, R * 1.001));
      globe.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), gratMat));
    }

    // city hubs and arcs
    const cities = { ...INDIA, ...WORLD };
    const hubGeo = new THREE.BufferGeometry();
    const names = Object.keys(cities);
    hubGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(names.flatMap((n) => toVec(...cities[n], R * 1.004).toArray())), 3));
    const hubSize = new Float32Array(names.map((n) => (n in INDIA ? 7 : 4.5)));
    hubGeo.setAttribute("aSize", new THREE.BufferAttribute(hubSize, 1));
    hubGeo.setAttribute("aSeed", new THREE.BufferAttribute(new Float32Array(names.map((_, i) => i / names.length)), 1));
    hubGeo.setAttribute("aColor", new THREE.BufferAttribute(new Float32Array(names.flatMap(() => [1, 0.95, 0.96])), 3));
    globe.add(new THREE.Points(hubGeo, dotMat));

    const links = [
      ["Delhi", "Mumbai"], ["Mumbai", "Bengaluru"], ["Delhi", "Kolkata"], ["Chennai", "Hyderabad"], ["Pune", "Ahmedabad"],
      ["Jaipur", "Lucknow"], ["Nagpur", "Kochi"], ["Delhi", "Dubai"], ["Mumbai", "Singapore"], ["Bengaluru", "London"],
      ["Chennai", "Singapore"], ["Kolkata", "Tokyo"], ["Delhi", "New York"], ["Hyderabad", "Nagpur"],
    ];
    const arcs = links.map(([a, b], i) => {
      const curve = arc(toVec(...cities[a]), toVec(...cities[b]), 0.3);
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(curve.getPoints(48)),
        new THREE.LineBasicMaterial({ color: 0xff3355, transparent: true, opacity: 0.22, blending: THREE.AdditiveBlending, depthWrite: false }));
      globe.add(line);
      const head = new THREE.Points(
        new THREE.BufferGeometry().setAttribute("position", new THREE.BufferAttribute(new Float32Array(3), 3))
          .setAttribute("aSize", new THREE.BufferAttribute(new Float32Array([6.5]), 1))
          .setAttribute("aSeed", new THREE.BufferAttribute(new Float32Array([0.5]), 1))
          .setAttribute("aColor", new THREE.BufferAttribute(new Float32Array([1, 0.85, 0.88]), 3)),
        dotMat);
      globe.add(head);
      return { curve, head, offset: (i * 0.37) % 1, speed: 0.1 + (i % 4) * 0.03 };
    });

    // drifting background specks
    const M = small ? 120 : 260, sp = new Float32Array(M * 3);
    for (let i = 0; i < M; i++) {
      const v = new THREE.Vector3().randomDirection().multiplyScalar(2.2 + Math.random() * 3.5);
      sp.set([v.x, v.y, v.z * 0.6 - 1], i * 3);
    }
    const spg = new THREE.BufferGeometry();
    spg.setAttribute("position", new THREE.BufferAttribute(sp, 3));
    const specks = new THREE.Points(spg, new THREE.PointsMaterial({ color: 0xff5470, size: 0.014, transparent: true, opacity: 0.55, depthWrite: false, blending: THREE.AdditiveBlending }));
    scene.add(specks);

    // layout: hero = big globe on the right; ambient = large, faint, off to the lower right
    const layout = () => {
      const w = el.clientWidth || 1, h = el.clientHeight || 1;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      const wide = w >= 960 && w / h > 1.1; // below 960px the page is one column, so the globe sits low and centred
      const s = hero ? (wide ? 1.3 : 1.0) : wide ? 1.2 : 1.0;
      globe.scale.setScalar(s);
      rimGroup.scale.setScalar(s);
      globe.position.set(hero ? (wide ? 1.45 : 0) : wide ? 1.75 : 0.5, hero ? (wide ? 0 : -0.6) : -0.85, 0);
      rimGroup.position.copy(globe.position);
    };
    const rimGroup = new THREE.Group();
    scene.children.filter((c) => c.isMesh && c.material.side === THREE.BackSide).forEach((m) => { scene.remove(m); rimGroup.add(m); });
    scene.add(rimGroup);
    layout();
    const ro = new ResizeObserver(layout);
    ro.observe(el);

    const target = { x: 0, y: 0 }, cur = { x: 0, y: 0 };
    const onMove = (e) => { target.x = (e.clientX / window.innerWidth - 0.5) * 2; target.y = (e.clientY / window.innerHeight - 0.5) * 2; };
    if (!reduce) window.addEventListener("pointermove", onMove, { passive: true });

    let raf = 0, last = performance.now(), t = 0, running = true;
    const base = -(79 * Math.PI) / 180;
    const frame = (now) => {
      raf = requestAnimationFrame(frame);
      if (!running) return;
      const dt = Math.min((now - last) / 1000, 0.05);
      last = now;
      t += dt;
      cur.x += (target.x - cur.x) * 0.04;
      cur.y += (target.y - cur.y) * 0.04;
      const sway = reduce ? 0 : Math.sin(t * 0.18) * 0.55;
      globe.rotation.y = base + sway + cur.x * 0.22;
      globe.rotation.x = 0.42 + cur.y * 0.12;
      rimGroup.rotation.y = globe.rotation.y;
      specks.rotation.y = t * 0.012;
      dotMat.uniforms.uTime.value = t;
      arcs.forEach((a) => {
        const p = (a.offset + t * a.speed) % 1;
        a.head.geometry.attributes.position.set(a.curve.getPoint(p).toArray());
        a.head.geometry.attributes.position.needsUpdate = true;
      });
      renderer.render(scene, camera);
    };
    raf = requestAnimationFrame(frame);
    if (reduce) { // draw one still frame, then stop spending battery
      setTimeout(() => { running = false; cancelAnimationFrame(raf); renderer.render(scene, camera); }, 120);
    }
    const onVis = () => { running = !document.hidden && !reduce; last = performance.now(); };
    document.addEventListener("visibilitychange", onVis);

    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("pointermove", onMove);
      ro.disconnect();
      scene.traverse((o) => { o.geometry?.dispose?.(); o.material?.dispose?.(); });
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [variant]);

  return <div ref={ref} className={`scene scene-${variant}`} aria-hidden="true" />;
}
