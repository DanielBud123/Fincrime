# Vendored libraries

Copied once from jsDelivr so that `ui/index.html` makes no network calls at runtime and still
works by double-clicking the file. Plain (UMD) builds, because browsers block `type="module"`
scripts on `file://`. The page degrades to a plain, animation-free screen if any of them is missing.

| File | Library | Version | Source | Licence | Used for |
|---|---|---|---|---|---|
| `gsap.min.js` | GSAP | 3.12.5 | `npm/gsap@3.12.5/dist/gsap.min.js` | GreenSock standard licence (free for this use) | timelines: panel transitions, rule-by-rule reveal, count-up, globe rotation |
| `motion.js` | Motion (motion.dev) | 12.23.26 | `npm/motion@12.23.26/dist/motion.js` | MIT | springs and gestures: badge pop, list stagger, press feedback |
| `three.min.js` | Three.js | r159 | `npm/three@0.159.0/build/three.min.js` | MIT | the globe showing the customer's and the hit's countries |

Three.js r159 is the last release that ships a UMD build (`three.min.js`); it logs one
deprecation warning on load, which is harmless. Do not edit these files; replace them whole.
