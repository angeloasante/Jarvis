---
name: frontend-design
description: Build beautiful modern UIs — landing pages, dashboards, components. Quality bar is a real startup site, not a tutorial project.
agents: [code_agent]
---

# Frontend Design

You are building production-quality UIs. The bar: would an investor take this seriously?

## Required Stack (every HTML file)

```html
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
```
After body close: `<script>lucide.createIcons();</script>`

NEVER use basic inline CSS. NEVER use default system fonts. NEVER skip Lucide icons.

## Dark Theme

```
Body:       bg-[#09090b] or bg-[#050507]
Cards:      bg-white/[0.02] border border-white/[0.04]
Borders:    border-white/5 (NOT border-gray-700)
Text:       text-gray-400 muted, text-white headings
Hover:      hover:border-indigo-500/30 hover:bg-white/[0.04]
```

## Landing Page Must Have

1. **Sticky frosted navbar** — `fixed top-0 bg-[#09090b]/70 backdrop-blur-xl border-b border-white/[0.04]`
2. **Hero with gradient text** — `bg-gradient-to-r from-X to-Y bg-clip-text text-transparent`
3. **Animated background** — gradient blobs with blur, subtle grid overlay, or particles
4. **Feature cards with Lucide icons** — `<i data-lucide="icon-name">` in colored icon boxes
5. **Stats/social proof** — numbers that prove traction
6. **CTA section** — gradient background, clear action
7. **Footer** — links, copyright, minimal

## What Makes It Look Pro vs Tutorial

| Tutorial (bad) | Pro (good) |
|----------------|------------|
| `background: #1a1a1a` | `bg-[#050507]` with gradient glow blobs |
| No navbar | Sticky frosted glass navbar |
| Basic `<h1>` | Gradient text with badge above it |
| Plain cards | Cards with icon boxes, hover border glow, stat footers |
| No animations | `fadeUp` animation with staggered delays |
| System font | Inter or Space Grotesk loaded from Google Fonts |
| Emoji icons | Lucide SVG icons in colored containers |
| `color: blue` | `text-indigo-400` with `bg-indigo-500/10` icon box |

## Animations (add these)

```css
@keyframes fadeUp { from { opacity:0; transform:translateY(30px); } to { opacity:1; transform:translateY(0); } }
@keyframes glow { 0%,100% { opacity:.3; } 50% { opacity:.6; } }
.fade-up { animation: fadeUp .7s ease-out forwards; }
.d1 { animation-delay:.1s; opacity:0; }
.d2 { animation-delay:.2s; opacity:0; }
.d3 { animation-delay:.3s; opacity:0; }
```

## Reference Template

There is a complete example at `friday/skills/frontend_design/template_landing.html`. Read it for inspiration on structure and Tailwind patterns. Don't copy it verbatim — be creative with colors, layout, and content. But match the quality bar.

## Quality Check

Before saving, verify:
- Does it have a navbar? (not just a floating title)
- Does the hero have visual depth? (gradient, blur, animation)
- Do cards have hover effects?
- Is there at least one animation?
- Would you show this to an investor?

If any answer is no, improve it before saving.
