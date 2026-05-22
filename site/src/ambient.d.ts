// Ambient (non-module) declarations for vendor JS packages that ship
// no own .d.ts. This file MUST stay free of imports/exports so its
// `declare module` statements remain GLOBAL ambient augmentations
// rather than scoped to a single module.

// The gl3d-only Plotly bundle ships only minified JS. UmapPanel uses
// it as a side-effect import (Plotly.newPlot, etc.).
declare module 'plotly.js-gl3d-dist-min';
