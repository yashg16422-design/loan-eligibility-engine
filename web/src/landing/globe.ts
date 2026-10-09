// The dotted Earth behind the opening: it spins, then the scroll locks it onto India (lit in
// the accent), zooms to Surat and raises a pin. Dots are Natural Earth land (public domain),
// sampled on a Fibonacci sphere, with denser layers for India and Surat that cross-fade in
// the shader so no patch edge shows. Loaded lazily: three.js is its own chunk.
import * as THREE from "three";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { D2R, decodeInt16, type GlobeData, latLonToXYZ, progress, smoothstep, SURAT } from "../lib/geo";
import { $, accent, isSmall, isStatic, THEME_EVENT } from "./dom";

const v3 = (lat: number, lon: number, r: number, out = new THREE.Vector3()): THREE.Vector3 =>
  out.set(...latLonToXYZ(lat, lon, r));

const DOT_VERT = /* glsl */ `
  attribute float aLayer, aSize, aFade;
  uniform float uPR, uScale, uIndia;
  uniform vec3 uLand, uAccent;
  varying vec3 vCol;
  varying float vA;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.);
    gl_Position = projectionMatrix * mv;
    float ind = step(.5, aLayer);
    vCol = mix(uLand, uAccent, ind * uIndia);
    // fade dots towards the limb, and dots too small to read
    float facing = dot(normalize(normalMatrix * position), normalize(-mv.xyz));
    float sz = aSize * uScale / -mv.z;
    vA = aFade * smoothstep(-.05, .35, facing) * mix(.8, 1., ind * uIndia) * clamp(sz * 1.3, .15, 1.);
    gl_PointSize = max(sz, 1.2) * uPR;
  }`;
const DOT_FRAG = /* glsl */ `
  varying vec3 vCol;
  varying float vA;
  void main() {
    float d = length(gl_PointCoord - .5);
    if (d > .5) discard;
    gl_FragColor = vec4(vCol, vA * smoothstep(.5, .28, d));
  }`;
const CITY_VERT = /* glsl */ `
  attribute float aW;
  uniform float uPR, uScale, uAmt;
  varying float vA;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.);
    gl_Position = projectionMatrix * mv;
    float facing = dot(normalize(normalMatrix * position), normalize(-mv.xyz));
    vA = uAmt * smoothstep(0., .3, facing) * (.35 + aW * .4);
    gl_PointSize = clamp((0.006 + aW * 0.006) * uScale / -mv.z, 2., 48.) * uPR;
  }`;
const CITY_FRAG = /* glsl */ `
  varying float vA;
  void main() {
    float d = length(gl_PointCoord - .5);
    gl_FragColor = vec4(1., .86, .5, exp(-d * d * 22.) * vA);
  }`;
const ATMO_VERT = /* glsl */ `
  varying vec3 vN;
  void main() { vN = normalize(normalMatrix * normal); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.); }`;
const ATMO_FRAG = /* glsl */ `
  uniform float uAmt;
  varying vec3 vN;
  void main() { float f = pow(clamp(.72 - vN.z, 0., 2.), 6.) * .16; gl_FragColor = vec4(.56, .66, 1., min(f, 1.) * uAmt); }`;

/** Scroll-driven state; GSAP tweens these numbers and the render loop reads them. */
interface GlobeState {
  lock: number; // 0 = idle spin, 1 = held on target
  aim: number; // how much the camera looks at the pin rather than the globe's centre
  lon: number;
  lat: number;
  dist: number;
  gx: number; // globe offset to the right on desktop, so the hero copy has room
  india: number;
  cities: number;
  pin: number;
}

function dotLayers(data: GlobeData): THREE.BufferGeometry {
  const pos: number[] = [], layer: number[] = [], size: number[] = [], fade: number[] = [];
  const v = new THREE.Vector3(), surat = v3(SURAT.lat, SURAT.lon, 1);
  // [data, layer id, dot size]: world, India (denser), Surat (densest, for the final zoom)
  const layers: Array<[string, number, number]> = [[data.land, 0, 0.0062], [data.india, 1, 0.0021], [data.guj, 2, 0.0007]];
  for (const [b64, id, s] of layers) {
    const a = decodeInt16(b64);
    for (let i = 0; i < a.length; i += 2) {
      v3(a[i] / 100, a[i + 1] / 100, 1, v);
      pos.push(v.x, v.y, v.z);
      layer.push(id);
      size.push(s);
      // radial cross-fade round Surat: India thins out where the dense layer takes over
      const g = smoothstep(2.1, 0.9, v.angleTo(surat) / D2R);
      fade.push(id === 2 ? g : id === 1 ? 1 - g * 0.92 : 1);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("aLayer", new THREE.Float32BufferAttribute(layer, 1));
  g.setAttribute("aSize", new THREE.Float32BufferAttribute(size, 1));
  g.setAttribute("aFade", new THREE.Float32BufferAttribute(fade, 1));
  return g;
}

function cityLights(data: GlobeData): THREE.BufferGeometry {
  const a = decodeInt16(data.cities), pos: number[] = [], w: number[] = [], v = new THREE.Vector3();
  for (let i = 0; i < a.length; i += 3) {
    v3(a[i] / 100, a[i + 1] / 100, 1.003, v);
    pos.push(v.x, v.y, v.z);
    w.push(a[i + 2] / 100);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("aW", new THREE.Float32BufferAttribute(w, 1));
  return g;
}

function starfield(): THREE.Points {
  const pos: number[] = [];
  for (let i = 0; i < 1800; i++) {
    const v = new THREE.Vector3().randomDirection().multiplyScalar(40 + Math.random() * 30);
    pos.push(v.x, v.y, v.z);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  return new THREE.Points(g, new THREE.PointsMaterial({ color: 0x8e8e8e, size: 1.2, sizeAttenuation: false, transparent: true, opacity: 0.45, depthWrite: false }));
}

/** Start the globe. Resolves false (and removes the canvas) when WebGL or the data is missing. */
export async function initGlobe(): Promise<boolean> {
  const canvas = $<HTMLCanvasElement>("#gl");
  let renderer: THREE.WebGLRenderer;
  let data: GlobeData;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
    const res = await fetch(`${import.meta.env.BASE_URL}geo/globe.json`);
    if (!res.ok) throw new Error(`globe data: HTTP ${res.status}`);
    data = (await res.json()) as GlobeData;
  } catch {
    canvas.remove(); // the page is designed to read fine on plain black
    return false;
  }

  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setClearColor(0x000000);
  const camera = new THREE.PerspectiveCamera(35, 1, 0.005, 120);
  const scene = new THREE.Scene();
  const G = new THREE.Group();
  scene.add(G, starfield());
  const pixelRatio = { value: renderer.getPixelRatio() }, pointScale = { value: 1 };

  G.add(new THREE.Mesh(new THREE.SphereGeometry(0.996, 96, 64), new THREE.MeshBasicMaterial({ color: 0x0b0d12 })));
  const dotMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, vertexShader: DOT_VERT, fragmentShader: DOT_FRAG,
    uniforms: { uPR: pixelRatio, uScale: pointScale, uIndia: { value: 0 }, uLand: { value: new THREE.Color("#8A8A8A") }, uAccent: { value: new THREE.Color(accent()) } },
  });
  G.add(new THREE.Points(dotLayers(data), dotMat));
  const cityMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, vertexShader: CITY_VERT, fragmentShader: CITY_FRAG,
    uniforms: { uPR: pixelRatio, uScale: pointScale, uAmt: { value: 0.35 } },
  });
  G.add(new THREE.Points(cityLights(data), cityMat));
  const atmoMat = new THREE.ShaderMaterial({
    side: THREE.BackSide, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: ATMO_VERT, fragmentShader: ATMO_FRAG, uniforms: { uAmt: { value: 1 } },
  });
  const atmo = new THREE.Mesh(new THREE.SphereGeometry(1, 64, 48), atmoMat);
  atmo.scale.setScalar(1.16);
  G.add(atmo);

  // the Surat pin: a beam, a head and a pulsing ring, standing on the surface normal
  const pin = new THREE.Group();
  const pinMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(accent()), transparent: true, opacity: 0 });
  const ringMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(accent()), transparent: true, side: THREE.DoubleSide, depthWrite: false });
  const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.0028, 0.0028, 1, 12), pinMat);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.011, 20, 16), pinMat);
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.8, 1, 48), ringMat);
  ring.rotation.x = -Math.PI / 2;
  pin.add(beam, head, ring);
  const surface = v3(SURAT.lat, SURAT.lon, 1);
  pin.position.copy(surface);
  pin.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), surface.clone().normalize());
  G.add(pin);
  addEventListener(THEME_EVENT, () => {
    const c = new THREE.Color(accent());
    dotMat.uniforms.uAccent.value.copy(c);
    pinMat.color.copy(c);
    ringMat.color.copy(c);
  });

  const S: GlobeState = { lock: 0, aim: 0, lon: 79, lat: 22, dist: 4.4, gx: 0.95, india: 0, cities: 0.35, pin: 0 };
  if (!isStatic()) {
    const tl = gsap.timeline({ defaults: { ease: "power2.inOut" } });
    tl.to(S, { lock: 1, lat: 21, dist: 2.6, gx: 0, india: 1, cities: 0.6, duration: 1 }, 0)
      .fromTo("#cap-india", { autoAlpha: 0, y: 20 }, { autoAlpha: 1, y: 0, duration: 0.3 }, 0.75)
      .to("#cap-india", { autoAlpha: 0, duration: 0.25 }, 1.45)
      // look at Surat from slightly south, so the pin stands up instead of pointing at us
      .to(S, { lon: SURAT.lon, lat: SURAT.lat - 7, dist: 1.2, pin: 1, aim: 1, cities: 1, duration: 1, ease: "power3.inOut" }, 1.4)
      .fromTo("#cap-surat", { autoAlpha: 0, y: 20 }, { autoAlpha: 1, y: 0, duration: 0.3 }, 2.2)
      .to(S, { dist: 1.09, lat: SURAT.lat - 3, duration: 0.6 }, 2.5)
      .to({}, { duration: 0.6 }, 2.95); // hold Surat in the centre; the section then scrolls away
    ScrollTrigger.create({ trigger: "#globe-beat", start: "top 60%", end: "bottom bottom", scrub: 0.7, animation: tl });
  }

  const resize = (): void => {
    const w = innerWidth, h = innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.fov = isSmall() ? 46 : 35;
    camera.updateProjectionMatrix();
    pointScale.value = h / (2 * Math.tan((camera.fov * D2R) / 2)); // world size -> pixels
  };
  addEventListener("resize", resize);
  resize();

  const statement = $("#statement"), ask = $("#ask");
  const pw = new THREE.Vector3(), look = new THREE.Vector3();
  let idle = 0, last = performance.now();
  const frame = (now: number): void => {
    const dt = Math.min((now - last) / 1000, 0.05), t = now / 1000;
    last = now;
    const vh = innerHeight;
    // step back while the statement is read, return for the zoom, then fade as #ask arrives
    const sr = statement.getBoundingClientRect();
    const dip = progress(vh * 0.85 - sr.top, 0, vh * 0.5) * progress(sr.bottom - vh * 0.15, 0, vh * 0.5);
    const away = progress(ask.getBoundingClientRect().top, 0, vh * 0.7);
    const opacity = (1 - 0.8 * dip) * away;
    canvas.style.opacity = String(opacity);
    if (opacity > 0.001) {
      if (!isStatic()) idle += dt * 9 * (1 - S.lock);
      const spin = (((idle % 360) + 540) % 360) - 180;
      const lon = S.lon + spin * (1 - S.lock);
      G.rotation.set(S.lat * D2R, -Math.PI / 2 - lon * D2R, 0);
      const gx = isSmall() ? 0 : S.gx, gy = isSmall() ? 0.62 * (1 - S.lock) : 0;
      G.position.set(gx, gy, 0);
      camera.position.set(0, 0, isSmall() ? S.dist * (1.3 - 0.27 * S.lock) : S.dist);
      G.updateMatrixWorld();
      pin.getWorldPosition(pw);
      camera.lookAt(look.set(gx * 0.35, gy * 0.6, 0).lerp(pw, S.aim * 0.85));
      dotMat.uniforms.uIndia.value = S.india;
      cityMat.uniforms.uAmt.value = S.cities;
      atmoMat.uniforms.uAmt.value = 1 - S.pin * 0.7;
      pin.scale.setScalar(Math.max(S.dist - 1, 0.03)); // constant on-screen size while zooming
      const bh = 0.32 * S.pin + 1e-4;
      beam.scale.y = bh;
      beam.position.y = bh / 2;
      head.position.y = bh;
      const pulse = (t * 0.6) % 1;
      ring.scale.setScalar(0.01 + pulse * 0.05);
      ringMat.opacity = (1 - pulse) * S.pin;
      pinMat.opacity = S.pin;
      renderer.render(scene, camera);
    }
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
  return true;
}
