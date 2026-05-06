// ──────────────────────────────────────────────────────────────────
// ANCHOR PANEL PATCH — insert this component block before the Sidebar
// function definition, and call <AnchorStatusPanel state={state}/> 
// inside Sidebar's Simulation section.
// ──────────────────────────────────────────────────────────────────

// The full AnchorStatusPanel component is in anchor_panel.js.
// In index.html, load it AFTER main.js with:
//   <script type="text/babel" src="/static/anchor_panel.js"></script>
// Then add <AnchorStatusPanel state={state}/> in the Sidebar render
// inside the "Simulation" section, before the Start/Stop buttons.
