<!-- Lines for system/README.md, under a "Demo" heading. Paste the two lines below the heading. -->

## Demo

Build the analyst screen's data after a run that wrote the diagnostics file (`python system/run dev output/dev.jsonl output/dev.diagnostics.jsonl`): `python tools/build_ui_data.py` embeds both output files into `ui/data.js` (local only, not committed); rebuild it after every run.
Then double-click `ui/index.html` (read-only, no server, no network: GSAP, Motion and Three.js are vendored in `ui/vendor/`); add a hit id to the address to open one case directly, for example `ui/index.html#H-582410`.
