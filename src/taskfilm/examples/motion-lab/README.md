# Motion lab

An original 24-second animation study: kinetic typography, a drawn and
interpolated SVG shape, three cards moving through perspective, and a type
lockup. It contains no screen recording and deliberately uses silence.

Run `taskfilm init demo` to copy this project with its fonts and notices, then:

```bash
taskfilm render demo/motion-lab --output motion-lab.mp4
```

Edit the scene HTML and paused GSAP timelines under `compositions/`. The root
mounts those scenes at 0, 6, 13 and 20 seconds. HyperFrames owns seeking and
rendering. This is HTML/SVG motion design; it does not import or execute Adobe
After Effects projects. GSAP is fetched from its pinned CDN at render time.
