---
name: newsletter-creator
description: "**Newsletter Creator**: Design, write, and build professional email newsletters and recurring newsletter templates. Produces beautiful, mobile-responsive HTML email layouts with compelling content structure, clear CTAs, and consistent branding. MANDATORY TRIGGERS: newsletter, email blast, email campaign, mailing list, subscriber email, weekly update, monthly digest, email template, Mailchimp, ConvertKit, Substack, email marketing. Also use when creating any recurring communication to a subscriber list, building email templates for the Transition Strategizer project, or designing any branded email communication. Even for 'just a quick email update to my list,' use this skill for professional results."
---

# Newsletter Creator

Create professional, engaging email newsletters that people actually want to open and read. This skill covers everything from one-off announcements to recurring newsletter templates with consistent branding.

## Core Philosophy

Email is intimate. It arrives in someone's personal inbox alongside messages from friends and family. A good newsletter respects that intimacy:
- It feels like it was written by a person, not a marketing department
- It delivers value before asking for anything
- It's scannable but rewards deeper reading
- It looks good on a phone (where 60%+ of email is read)
- It loads instantly, even on slow connections

## Email HTML vs Web HTML

Email HTML is a different beast from web HTML. Email clients (Gmail, Outlook, Apple Mail, Yahoo) each render HTML differently, and most strip out modern CSS. The rules:

### What Works Everywhere
- Inline CSS (style="" attributes on every element)
- Table-based layouts (yes, still, in 2026)
- Web-safe fonts + fallbacks
- Basic CSS: color, background-color, font-size, font-family, font-weight, padding, margin, border, text-align, line-height, width, max-width
- `<img>` tags with explicit width and height
- `<a>` tags with inline color styling
- Background colors on `<td>` elements

### What Breaks in Email
- CSS Grid and Flexbox (limited support)
- External stylesheets (Gmail strips `<link>` tags)
- `<style>` blocks (partially supported — use as progressive enhancement only)
- CSS variables (custom properties)
- position: absolute/fixed/sticky
- JavaScript (completely stripped)
- SVG (inconsistent)
- `<video>` and `<audio>`
- CSS animations/transitions
- overflow: hidden (inconsistent)
- max-width without width (Outlook ignores max-width)

### The Hybrid Approach

Use tables for structure but write clean, semantic HTML where possible. Add a `<style>` block for clients that support it (Apple Mail, iOS Mail, some Android) as progressive enhancement:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Newsletter Title — Preview Text Goes Here</title>
  <!--[if mso]>
  <style>table{border-collapse:collapse;}td{font-family:Arial,sans-serif;}</style>
  <![endif]-->
  <style>
    /* Progressive enhancement for modern clients */
    @media screen and (max-width: 600px) {
      .container { width: 100% !important; }
      .stack { display: block !important; width: 100% !important; }
      .mobile-padding { padding: 16px !important; }
    }
  </style>
</head>
```

## Newsletter Structure

### Standard Layout Template

```
┌─────────────────────────────┐
│         PREHEADER           │ ← Hidden preview text
├─────────────────────────────┤
│           LOGO              │
│        + Nav links          │
├─────────────────────────────┤
│                             │
│       HERO / FEATURE        │
│    Headline + Image + CTA   │
│                             │
├─────────────────────────────┤
│                             │
│      CONTENT SECTIONS       │
│   2-3 articles/updates      │
│   with images + read more   │
│                             │
├─────────────────────────────┤
│                             │
│     SECONDARY CONTENT       │
│  Quick links, tips, quotes  │
│                             │
├─────────────────────────────┤
│          CTA BLOCK          │
│   Clear call to action      │
├─────────────────────────────┤
│          FOOTER             │
│  Social links, unsubscribe  │
│  Physical address (required)│
└─────────────────────────────┘
```

### Preheader Text

The most overlooked element. This appears in email client previews alongside the subject line. Write it intentionally:

```html
<!-- Visible preheader -->
<div style="max-height:0;overflow:hidden;mso-hide:all;font-size:1px;color:#fafafa;line-height:1px;">
  Your preview text goes here — make it compelling, 85-100 characters.
  &zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp; <!-- padding to push away footer text -->
</div>
```

### Content Width

- **Max width: 600px** — this is the email standard. Some modern templates push to 640px, but 600px is safest.
- **Mobile: 100%** with 16px padding on each side (effective content width: ~343px on iPhone)

## Writing for Newsletters

### Subject Lines
- 6-10 words (40-60 characters)
- Front-load the interesting part
- Avoid spam triggers: ALL CAPS, excessive punctuation!!!, "Free", "Act now"
- Test: would you open this if it appeared between messages from friends?

### Body Content
- Lead with the most valuable/interesting item
- Short paragraphs (2-3 sentences max)
- One idea per paragraph
- Use subheadings to enable scanning
- Personal tone — write as "I" to "you"
- Include one clear primary CTA per newsletter
- Secondary CTAs can exist but shouldn't compete

### Content-to-Promotion Ratio
- At least 80% value, no more than 20% ask
- Lead with what's useful to the reader
- If promoting something, frame it as "here's something that might help you"

## Visual Design

### Color in Email
Keep it simple. Most newsletters work best with:
- White or very light background
- One brand accent color for headers and CTAs
- Dark text on light background (never the reverse for body text)
- CTA buttons in the accent color with white text

### Images
- Always include `alt` text (some clients block images by default)
- Use `width` and `height` attributes (Outlook needs these)
- Keep total email size under 102KB — Gmail clips larger emails
- Host images externally (Cloudinary, S3, or your email platform)
- Don't rely on images to convey critical information

### Buttons (CTA)
Bulletproof buttons using `<table>` (works in Outlook):

```html
<table border="0" cellpadding="0" cellspacing="0" role="presentation">
  <tr>
    <td align="center" style="border-radius:6px;background-color:#2563eb;">
      <a href="https://yourlink.com" target="_blank"
         style="display:inline-block;padding:14px 32px;font-family:Arial,sans-serif;
                font-size:16px;font-weight:bold;color:#ffffff;text-decoration:none;
                border-radius:6px;background-color:#2563eb;">
        Your CTA Text
      </a>
    </td>
  </tr>
</table>
```

## Newsletter Types

### Weekly/Monthly Update
Personal tone, recurring structure readers learn to expect. Sections might include: main article, quick links, a personal note, upcoming events. Consistency in format builds habit.

### Product/Service Announcement
Hero image + clear value proposition + single CTA. Keep it focused. One message, one action.

### Educational/Content Newsletter
Longer form, more like a blog post delivered to inbox. Can include original writing, curated links, commentary. The value IS the email — it's not driving somewhere else.

### Event Invitation
Date/time prominent, clear RSVP/register button, brief description of what and why, social proof if available (speakers, past attendees).

## Platform-Specific Notes

### Mailchimp
- Use their template builder for quick results, or paste custom HTML
- Merge tags: `*|FNAME|*`, `*|MC:SUBJECT|*`, `*|UNSUB|*`
- Test with their preview/inbox testing tools before sending
- Free tier: up to 500 contacts

### ConvertKit / Kit
- Focuses on plain-text-style emails (high deliverability)
- Good for creator/personal brand newsletters
- Supports basic HTML templates
- Free tier: up to 10,000 subscribers

### Substack
- Minimal customization but high deliverability
- Built-in paid subscription model
- Good for content-first newsletters
- No custom HTML — their editor only

### Self-Hosted (Buttondown, Ghost, Listmonk)
- Full control over design and data
- Requires more technical setup
- Aligns with Barak's preference for independence from platforms

## Legal Requirements

Every marketing email MUST include:
- **Physical mailing address** (CAN-SPAM requirement)
- **Unsubscribe link** that works within 10 business days
- **Accurate sender information** (From name and address)
- If applicable: **GDPR consent** notice for EU recipients

## Testing Checklist

Before sending any newsletter:
- [ ] Subject line is compelling and under 60 characters
- [ ] Preheader text is intentional (not auto-generated from body)
- [ ] All links work and go to correct destinations
- [ ] Images have alt text and display correctly
- [ ] Renders well in Gmail, Apple Mail, and Outlook (test or preview)
- [ ] Mobile layout is clean at 375px width
- [ ] CTA buttons are large enough to tap (min 44px height)
- [ ] Unsubscribe link is present and functional
- [ ] Physical address is included
- [ ] Total email size is under 102KB
- [ ] Spelling and grammar checked
- [ ] Sent to test address first

## Output Format

When creating a newsletter, deliver:
1. The HTML file (single file, all styles inline)
2. A plain-text version (for accessibility and deliverability)
3. Suggested subject line + preheader text
4. Notes on any images needed (with recommended dimensions)

Save to the appropriate project directory. If this is a template for recurring use, include clear comments in the HTML marking where content should be updated each issue.
