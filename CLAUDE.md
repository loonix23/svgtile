# svgtile

CLI that splits an SVG (sewing patterns, often FreeCAD TechDraw exports) into
glue-together paper sheets as a PDF at true 1:1 scale. User-facing docs: README.md.

## Layout

- `svgpath.py` — SVG path `d` parser -> polylines.
- `svgdoc.py` — SVG document -> polylines in **cm**, scale/unit resolution, transforms, styles.
- `svgtile.py` — CLI, tiling, registration marks, PDF output (reportlab).
- `svgtile-standalone.py` — **generated** single-file build. Never edit by hand;
  edit the modules, then run `python3 build_standalone.py`.
- `test_svgtile.py` — self-test script (not pytest); also fails if the standalone is stale.
- `examples/` — demo SVG and its tiled PDF. Regenerate the PDF when output changes.
  Patterns being tiled are user data: never commit them (see `.gitignore`).

## Commands

```bash
python3 build_standalone.py                     # regenerate standalone after any module change
python3 svgtile.py examples/demo.svg -o examples/demo.pdf --title "svgtile demo"   # regenerate the example
python3 test_svgtile.py   # needs pypdf, numpy, and pdftoppm (poppler)
```

## Invariants — don't break these

- Scale correctness is the whole point: everything internal is in cm; never let
  a change silently alter scale. Report the scale basis.
- Output is monochrome (black only) — laser-printer safe.
- Registration marks are generated in master coordinates so both sheets sharing a
  glue band emit the identical mark. Keep pairing structural.
- Sheet numbering: 1 = top-left, reading order (`sheet_no`). Master y grows upward
  in PDF space, so row 0 is the *bottom* row.
- Dependencies stay at `reportlab` + `lxml` for the tool itself.
- When adding a CLI flag, update the README options table too.
