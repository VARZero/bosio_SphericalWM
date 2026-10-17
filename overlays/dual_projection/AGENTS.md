# Core design contract

The user's main concept is incremental tiled rendering, not full-window rendering
on every change. Preserve it across hardware/software integration and optimization.

- Cache projected window tiles and reuse unchanged layers, including under overlap.
- Map actual surface changes to affected destination tiles; include bilinear footprints.
- Recompose only affected tiles for move, visibility, order, cursor and content changes.
- No visual change means zero projector jobs and no output-buffer commit.
- Update only changed payload/directory ranges after the initial snapshot. Preserve
  frame-atomic double-buffer handoff and buffer lifetime until hardware completion.
- Validate partial results against full recomposition and record actual job/tile counts.
- Full rebuilding is for initial state, explicit full snapshots, or recovery; do not
  silently make it the normal update path again.
