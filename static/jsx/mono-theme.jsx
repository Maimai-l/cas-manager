// ── Mono prototype theme tokens ────────────────────────────────────────
// Single source of truth. Swap accent later via a theme switch — but for
// now hard-coded to chartreuse green.

const MONO_ACCENT = {
  solid:    "#b1e245",
  onAccent: "#1f2a08",
  shadow:   "0 1px 3px rgba(90,120,30,0.22), inset 0 0.5px 0 rgba(255,255,255,0.4)",
};

const MONO_NEUTRALS = {
  bg:       "#fafafa",
  glass:    "rgba(255,255,255,0.55)",
  card:     "rgba(255,255,255,0.78)",
  inkDeep:  "rgba(20,20,20,0.95)",
  ink:      "rgba(20,20,20,0.85)",
  inkMid:   "rgba(20,20,20,0.6)",
  inkSoft:  "rgba(20,20,20,0.5)",
  hairline: "rgba(0,0,0,0.06)",
  hairOnGlass: "rgba(0,0,0,0.05)",
  chipBg:   "rgba(0,0,0,0.05)",
  chipBgHi: "rgba(0,0,0,0.08)",
};

// Strand metadata — mono. Icon only, no colored chip.
const MONO_STRAND = {
  creativity: { label: "Creativity", icon: "creativity" },
  activity:   { label: "Activity",   icon: "activity"   },
  service:    { label: "Service",    icon: "service"    },
};

window.MONO_ACCENT = MONO_ACCENT;
window.MONO_NEUTRALS = MONO_NEUTRALS;
window.MONO_STRAND = MONO_STRAND;

// Context for modal navigation — same shape as old prototype
window.MonoCtx = React.createContext({ close: () => {}, go: () => {} });
