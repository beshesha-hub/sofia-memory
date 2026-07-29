---
name: app-store-deploy
description: >
  **App Store Deployment Guide**: Complete end-to-end guidance for publishing apps to major app stores
  (Apple App Store, Google Play Store, Amazon Appstore). Covers the FULL pipeline — not just code
  signing and uploading, but also account setup, business registration, tax/banking configuration,
  store listing optimization, screenshot requirements, privacy policy creation, review guidelines,
  post-launch monitoring, and updates. Use this skill whenever the user mentions: publishing an app,
  submitting to app store, deploying to Play Store, app store listing, app review process, app
  store rejection, TestFlight, Google Play Console, app store optimization (ASO), app pricing,
  in-app purchases setup, app store screenshots, app privacy labels, app content rating, or
  anything related to getting an app from "it works on my device" to "people can download it."
  Even for "I just need to upload my app," use this skill — there's always more to it than people expect.
---

# App Store Deployment Skill

This skill guides you through the complete process of deploying apps to major app stores. It covers everything from initial account setup through post-launch maintenance, including the administrative, legal, and procedural steps that developers often discover too late.

## Why This Skill Exists

Getting an app to "work" is maybe 60% of the job. The other 40% is navigating account setup, business registration, tax configuration, store listings, screenshots, privacy policies, content ratings, review guidelines, and the actual submission process. Each store has its own requirements, timelines, and gotchas. This skill captures all of that so you don't discover requirements at the moment of rejection.

## How to Use This Skill

1. **Determine target stores** — Ask the user which stores they're targeting (iOS, Android, Amazon, or all three)
2. **Assess readiness** — Walk through the pre-submission checklist for their target stores
3. **Guide sequentially** — Work through the phases in order: Account → Legal → Build → Listing → Submit → Monitor
4. **Read the relevant reference file** for store-specific details before giving guidance
5. **Be explicit about costs and timelines** — These are the things that surprise people most

## Reference Files

Read the relevant reference file for the store the user is deploying to:

- `references/apple.md` — Apple App Store (iOS, iPadOS, macOS, tvOS, watchOS, visionOS)
- `references/google.md` — Google Play Store (Android)
- `references/amazon.md` — Amazon Appstore (Fire OS, Fire TV)

Read ALL relevant reference files if the user is doing a multi-store launch. Don't assume requirements are the same across stores — they differ in important ways.

## Universal Deployment Phases

These phases apply regardless of which store you're targeting. Store-specific details are in the reference files.

### Phase 1: Account & Business Setup

Before you write a single line of store listing copy, you need:

- **Developer account** for each target store (Apple charges $99/year, Google charges $25 one-time, Amazon is free)
- **Business entity decision** — Individual or Organization? Organization accounts require a D-U-N-S number (Apple) or business verification (Google). This matters for how your developer name appears on the store and for tax purposes.
- **Tax and banking setup** — Every store requires you to configure tax information and a bank account for receiving payments, even for free apps (some stores require it before you can submit anything)
- **Legal entity** — If you're selling apps or have in-app purchases, you need to understand the tax implications in your jurisdiction. Consider whether you need an LLC or similar entity.

The account setup process can take days to weeks (especially the D-U-N-S number for Apple, which can take up to 30 days). Start this FIRST, before everything else.

### Phase 2: Legal Requirements

Every app store requires, at minimum:

- **Privacy Policy** — A publicly accessible URL describing what data you collect, how you use it, and how users can request deletion. Required even if you collect zero data (you still need to say that). Host it on a stable URL that won't go down.
- **Terms of Service** — Recommended for any app with user accounts or user-generated content. Required for some app categories.
- **Data Safety / Privacy Labels** — Each store has its own format for declaring your data practices. These must be accurate — inconsistencies with actual app behavior are a common rejection reason.
- **COPPA / Children's Privacy** — If your app could be used by children under 13 (or the applicable age in your jurisdiction), additional requirements apply. This is a legal minefield — get it right.
- **GDPR / Regional Compliance** — If your app is available in the EU, GDPR applies. California has CCPA. Other jurisdictions have their own rules.

### Phase 3: Build Preparation

Before submitting your binary:

- **Target the correct SDK version** — Each store has minimum SDK requirements that change regularly. Check the reference files for current requirements.
- **Code signing** — Apple requires provisioning profiles and certificates. Android requires a signing key. Get this set up properly — key management is critical and mistakes are sometimes irreversible.
- **App size optimization** — Large apps get download warnings or require WiFi. Optimize assets, use app thinning (iOS) or Android App Bundles (Android).
- **Remove all debug code** — No test APIs, no debug menus, no placeholder content. Reviewers will find it.
- **Test on physical devices** — Simulators are not sufficient. Amazon explicitly requires physical device testing.
- **Accessibility** — Not always required for approval, but increasingly expected and the right thing to do.

### Phase 4: Store Listing

Your store listing is your marketing. Every store requires:

- **App name** (character limits vary by store)
- **Description** (short and long versions)
- **Screenshots** — Each store has specific size requirements, device frame requirements, and minimum counts. This is where many developers spend more time than expected. See reference files for exact specs.
- **App icon** — Must meet exact size and format specifications. No alpha transparency on iOS.
- **Category selection** — Choose carefully; it affects discoverability
- **Keywords / Tags** — Critical for search visibility
- **Content rating** — Complete the rating questionnaire honestly. Getting this wrong can result in removal.
- **Pricing and availability** — Decide on free vs. paid, and which countries/regions to target
- **What's New / Release Notes** — Required for updates, good practice for initial release

### Phase 5: Submission & Review

- **Review timelines** — Apple: ~90% within 24 hours, can be 2-5 days. Google: typically 1-3 days, longer for new accounts. Amazon: varies, typically 1-5 days.
- **Common rejection reasons** — Crashes, incomplete functionality, privacy policy issues, misleading metadata, not declaring permissions correctly. See reference files for store-specific rejection patterns.
- **Appeal process** — If rejected, read the rejection reason carefully. Each store has a resolution center or appeal mechanism.
- **Staged rollout** — Google and Apple both offer phased release options. Use them for major updates.

### Phase 6: Post-Launch

- **Monitor reviews and ratings** — Respond to user feedback promptly
- **Crash reporting** — Set up crash monitoring (Firebase Crashlytics, Sentry, etc.)
- **Update regularly** — Apps that aren't updated may be flagged or removed
- **SDK requirements change** — Stores regularly update minimum SDK targets. Stay current or your app will eventually be rejected for updates.
- **Policy changes** — All stores update their policies. Subscribe to developer newsletters.

## Multi-Store Launch Strategy

If deploying to multiple stores simultaneously:

1. Start with the store that has the longest setup time (usually Apple due to the D-U-N-S number and annual review)
2. Prepare store listings in parallel — much of the content (descriptions, screenshots concepts) can be shared, but sizes and formats differ
3. Submit to all stores around the same time, but expect different approval timelines
4. Plan your marketing launch date around the slowest approval, with buffer

## AI-Specific Requirements (2026)

As of 2026, both Apple and Google have specific requirements for apps that use AI:

- **Disclosure** — You must explain to users when content is AI-generated
- **Content moderation** — AI-generated content must be moderated to prevent harmful outputs
- **Privacy** — If AI features process user data, this must be declared in your privacy labels
- **Apple specific** — Apps using generative AI must include content filtering and must not generate harmful content
- **Google specific** — Apps must handle AI-generated content responsibly per Google's AI policy guidelines

## Cost Summary

| Item | Apple | Google | Amazon |
|------|-------|--------|--------|
| Developer Account | $99/year | $25 one-time | Free |
| D-U-N-S Number | Free but slow | N/A | N/A |
| Code Signing | Included with account | Free (your own key) | Uses Android signing |
| App Hosting | Included | Included | Included |
| Revenue Share | 70/30 (85/15 for small business) | 70/30 (85/15 for <$1M) | 70/30 |

## When Things Go Wrong

Common emergencies and how to handle them:

- **Rejected for privacy** — Most common. Review your privacy labels, ensure your privacy policy URL works, and make sure your actual data collection matches what you declared.
- **Signing key lost** — On Android, this can be catastrophic. Use Google Play App Signing to let Google manage your upload key. On iOS, certificates can be regenerated through the developer portal.
- **App removed from store** — Don't panic. Read the notification carefully, fix the issue, and resubmit. You usually have a grace period.
- **Bad reviews flooding in** — Respond professionally, fix bugs quickly, push an update.
