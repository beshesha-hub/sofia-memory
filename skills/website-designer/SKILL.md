---
name: website-designer
description: "**Advanced Website Designer & Implementer**: Design and build complete, engaging, professional websites from scratch or from requirements. Produces fully functional HTML/CSS/JavaScript sites optimized for responsiveness, accessibility, performance, and visual appeal. MANDATORY TRIGGERS: website, web page, landing page, site design, web design, homepage, portfolio site, business site, build a site, create a website, multi-page site, responsive design, web layout. Also use when the user mentions Transition Strategizer, business development website, or any project that needs a web presence. Even if the user says 'simple page' or 'quick site,' use this skill — it ensures quality foundations."
---

# Advanced Website Designer & Implementer

Build complete, professional, engaging websites that work beautifully across devices. This skill covers everything from single-page landing pages to multi-page sites with navigation, animations, forms, and rich interactivity.

## Core Philosophy

Great websites share these qualities regardless of scale:
- They load fast and feel responsive to interaction
- They look intentional on every screen size, from phone to ultrawide
- They guide the visitor's eye and attention through visual hierarchy
- They're accessible to people using keyboards, screen readers, and assistive tech
- They feel alive — subtle motion, thoughtful hover states, purposeful transitions

The goal is never just "a page that works." It's a page that makes someone want to stay.

## Architecture Decisions

### Single-File vs Multi-File

**Single HTML file** (default for most projects): When the site is 1-5 pages, embed CSS in `<style>` and JS in `<script>` tags. This makes the file portable, easy to share, and immediately functional when opened in a browser. Use this for landing pages, portfolios, project showcases, and small business sites.

**Multi-file structure** for larger projects:
```
site/
├── index.html
├── css/
│   └── styles.css
├── js/
│   └── main.js
├── images/
└── pages/
    ├── about.html
    └── contact.html
```

### Framework Choice

For most projects Barak and Sofia work on, **vanilla HTML/CSS/JS is preferred** — no build tools, no npm, no frameworks. This aligns with the principle of minimizing external dependencies.

Use external libraries only when they save significant effort:
- **Google Fonts** via CDN for typography
- **Font Awesome** or **Lucide** for icons (CDN)
- **GSAP** for complex animations (CDN)
- **Three.js** for 3D elements (CDN)

Never require a build step. The site should work by opening the HTML file directly.

## Design System Foundations

### Typography

Choose a type pairing that establishes personality immediately:

```css
/* Professional/Warm — good for consulting, coaching, personal brands */
--font-heading: 'Playfair Display', Georgia, serif;
--font-body: 'Inter', -apple-system, sans-serif;

/* Modern/Clean — good for tech, startups, portfolios */
--font-heading: 'Space Grotesk', sans-serif;
--font-body: 'DM Sans', -apple-system, sans-serif;

/* Approachable/Human — good for community, wellness, creative */
--font-heading: 'Outfit', sans-serif;
--font-body: 'Source Sans 3', -apple-system, sans-serif;
```

Type scale using clamp() for fluid sizing:
```css
--text-xs: clamp(0.75rem, 0.7rem + 0.25vw, 0.875rem);
--text-sm: clamp(0.875rem, 0.8rem + 0.35vw, 1rem);
--text-base: clamp(1rem, 0.9rem + 0.5vw, 1.125rem);
--text-lg: clamp(1.125rem, 1rem + 0.6vw, 1.25rem);
--text-xl: clamp(1.25rem, 1.1rem + 0.75vw, 1.5rem);
--text-2xl: clamp(1.5rem, 1.2rem + 1.5vw, 2.25rem);
--text-3xl: clamp(2rem, 1.5rem + 2.5vw, 3.5rem);
--text-hero: clamp(2.5rem, 2rem + 3vw, 5rem);
```

### Color Strategy

Always define colors as CSS custom properties. Build from a core palette:

```css
:root {
  /* Core brand colors */
  --color-primary: #2563eb;
  --color-primary-dark: #1e40af;
  --color-primary-light: #93c5fd;

  /* Neutrals — warm grays feel more human */
  --color-bg: #fafaf9;
  --color-surface: #ffffff;
  --color-text: #1c1917;
  --color-text-muted: #57534e;
  --color-border: #e7e5e4;

  /* Accent — use sparingly for CTAs and highlights */
  --color-accent: #f59e0b;

  /* Semantic */
  --color-success: #16a34a;
  --color-error: #dc2626;
}
```

### Spacing & Layout

Use a consistent spacing scale:
```css
--space-1: 0.25rem;  /* 4px */
--space-2: 0.5rem;   /* 8px */
--space-3: 0.75rem;  /* 12px */
--space-4: 1rem;     /* 16px */
--space-6: 1.5rem;   /* 24px */
--space-8: 2rem;     /* 32px */
--space-12: 3rem;    /* 48px */
--space-16: 4rem;    /* 64px */
--space-24: 6rem;    /* 96px */
--space-32: 8rem;    /* 128px */
```

Section padding pattern:
```css
.section { padding: var(--space-24) var(--space-4); }
.container { max-width: 1200px; margin: 0 auto; padding: 0 var(--space-6); }
```

## Responsive Design

### Mobile-First Approach

Write base styles for mobile, then layer on complexity:

```css
/* Base: mobile (320px+) */
.grid { display: grid; gap: var(--space-6); }

/* Tablet (768px+) */
@media (min-width: 768px) {
  .grid { grid-template-columns: repeat(2, 1fr); }
}

/* Desktop (1024px+) */
@media (min-width: 1024px) {
  .grid { grid-template-columns: repeat(3, 1fr); }
}
```

### Key Breakpoints
- **480px** — Large phones
- **768px** — Tablets / small laptops
- **1024px** — Desktop
- **1280px** — Large desktop
- **1536px** — Ultrawide (max-width container)

### Navigation Pattern

Mobile: hamburger menu with slide-in panel. Desktop: horizontal nav. Always include:

```css
/* Sticky header with blur effect */
.header {
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--color-border);
}
```

## Engagement Patterns

### Hero Sections

The hero is the first 3 seconds. Make it count:
- Clear headline that states the value proposition
- Supporting subtext (1-2 sentences max)
- One primary CTA button, optionally one secondary
- Visual element (image, illustration, animation, or gradient)
- Enough whitespace that nothing feels cramped

### Scroll Animations

Use Intersection Observer for reveal-on-scroll (no library needed):

```javascript
const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('visible');
      observer.unobserve(entry.target);
    }
  });
}, { threshold: 0.1, rootMargin: '0px 0px -50px 0px' });

document.querySelectorAll('.animate-in').forEach(el => observer.observe(el));
```

```css
.animate-in {
  opacity: 0;
  transform: translateY(30px);
  transition: opacity 0.6s ease, transform 0.6s ease;
}
.animate-in.visible {
  opacity: 1;
  transform: translateY(0);
}
```

### Micro-Interactions

Buttons, links, and cards should respond to interaction:

```css
.btn {
  transition: all 0.2s ease;
}
.btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}
.btn:active {
  transform: translateY(0);
}

.card {
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}
.card:hover {
  transform: translateY(-4px);
  box-shadow: 0 12px 24px rgba(0,0,0,0.1);
}
```

## Accessibility Checklist

Every site must meet these minimums:
- Color contrast ratio ≥ 4.5:1 for body text, ≥ 3:1 for large text
- All images have meaningful alt text (or alt="" for decorative)
- Keyboard navigation works for all interactive elements
- Focus states are visible and clear
- Skip-to-content link for screen readers
- Semantic HTML: `<header>`, `<nav>`, `<main>`, `<section>`, `<footer>`
- Form inputs have associated `<label>` elements
- ARIA attributes where semantic HTML isn't sufficient
- `prefers-reduced-motion` respected for animations
- `prefers-color-scheme` supported if dark mode is included

## Performance

- Images: use modern formats (WebP/AVIF) with `<picture>` fallbacks, lazy-load below fold
- Fonts: `font-display: swap`, preload critical fonts, limit to 2-3 weights
- CSS: no unused styles, minimize specificity battles
- JS: defer non-critical scripts, keep initial bundle minimal
- Target: Lighthouse score ≥ 90 on all metrics

## Common Page Types

### Landing Page
Hero → Problem/Pain → Solution → Features/Benefits → Social Proof → CTA → Footer

### About Page
Story/Mission → Team/Person → Values → Timeline/History → CTA

### Services/Offerings Page
Overview → Service Cards → Process → Pricing (if applicable) → FAQ → CTA

### Contact Page
Brief intro → Contact Form → Alternative contact methods → Map (if relevant)

### Portfolio/Gallery
Filterable grid → Project detail modal or page → Testimonials

## Deployment Notes

For Barak's projects, sites will typically be:
- Opened directly as local HTML files (simplest)
- Hosted on GitHub Pages (free, version-controlled)
- Hosted on Netlify or Vercel (free tier, auto-deploy from git)

Always ensure the site works when opened directly as a file (file:// protocol) unless it requires server-side features.

## Output Checklist

Before delivering any website, verify:
- [ ] Opens correctly in browser
- [ ] Responsive at 375px, 768px, 1024px, 1440px
- [ ] All links and navigation work
- [ ] Forms have validation and clear error states
- [ ] Animations respect prefers-reduced-motion
- [ ] Text is readable and hierarchy is clear
- [ ] CTAs are prominent and above the fold
- [ ] Footer includes all necessary links/info
- [ ] No console errors
- [ ] File is saved to the appropriate project directory
