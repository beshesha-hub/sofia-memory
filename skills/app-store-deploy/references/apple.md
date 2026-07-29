# Apple App Store — Detailed Reference

## Account Setup

1. **Enroll in Apple Developer Program** at developer.apple.com ($99/year)
2. **Individual vs Organization**: Organization requires a D-U-N-S number (free from Dun & Bradstreet but takes up to 30 days). Organization accounts show your company name; individual accounts show your personal name.
3. **Two-factor authentication** is required for your Apple ID
4. **Agreements** — Accept the latest Apple Developer Program License Agreement in App Store Connect. Also complete the Paid Applications agreement (even for free apps if you ever want to add in-app purchases)
5. **Tax & Banking** — Configure in App Store Connect under Agreements, Tax, and Banking. Required before you can distribute paid apps or apps with in-app purchases.

## Current SDK Requirements (as of April 2026)

- iOS/iPadOS apps: built with iOS & iPadOS 26 SDK (Xcode 26)
- tvOS apps: tvOS 26 SDK
- watchOS apps: watchOS 26 SDK
- visionOS apps: visionOS 26 SDK
- This requirement takes effect April 28, 2026
- Apps can still support older iOS versions as deployment targets — only the build SDK must be current

## Build Requirements

- **Xcode**: Must use latest stable Xcode (Xcode 26 as of April 2026)
- **Architecture**: 64-bit only (32-bit support dropped years ago)
- **App Bundle**: .ipa file uploaded through Xcode or Transporter
- **Code Signing**: Requires an Apple Distribution certificate and provisioning profile. Manage these in the Apple Developer portal or through Xcode's automatic signing.
- **App Thinning**: Use asset catalogs and app slicing to reduce download size per device
- **Bitcode**: No longer required (deprecated in Xcode 14)

## Certificates & Provisioning — Step by Step

1. In Xcode → Preferences → Accounts, add your Apple ID
2. Select your team, then "Manage Certificates"
3. Create an Apple Distribution certificate if you don't have one
4. Create an App ID in the Developer Portal (Identifiers section)
5. Create a provisioning profile that links your certificate to your App ID
6. Or: let Xcode handle all of this with "Automatically manage signing" (recommended for most cases)

## App Store Connect Setup

1. Go to appstoreconnect.apple.com
2. Click "My Apps" → "+" → "New App"
3. Fill in: Platform, Name, Primary Language, Bundle ID, SKU
4. **Bundle ID** must match what's in your Xcode project
5. **SKU** is your internal identifier (not shown to users)

## Store Listing Requirements

### Screenshots
- **Required sizes**: 6.9" display (iPhone 16 Pro Max), 6.7" display (iPhone 16 Plus), 6.5" display, 5.5" display. iPad Pro 12.9" (6th gen and 2nd gen) for iPad apps.
- **Count**: 1-10 screenshots per device size
- **Format**: PNG or JPEG, no alpha
- **Orientation**: Match your app's orientation
- **Pro tip**: Design one set of screenshots at the largest size and App Store Connect can auto-scale for smaller sizes (with some caveats)

### App Preview Videos
- Optional but highly recommended
- Up to 3 videos per localization per device size
- 15-30 seconds, no outside footage
- Must show actual app functionality

### Icons
- 1024x1024 PNG, no alpha, no rounded corners (Apple applies the mask)
- Must match the icon in your app binary

### Text
- **App Name**: Up to 30 characters
- **Subtitle**: Up to 30 characters (important for ASO)
- **Promotional Text**: Up to 170 characters (can be updated without new binary)
- **Description**: Up to 4000 characters
- **Keywords**: Up to 100 characters, comma-separated
- **What's New**: Up to 4000 characters

## Privacy Requirements (2026)

- **Privacy Nutrition Labels**: Declare all data types your app collects, organized by: Data Used to Track You, Data Linked to You, Data Not Linked to You
- **Privacy Manifest** (PrivacyInfo.xcprivacy): Required for apps and third-party SDKs that access certain APIs. Must declare which APIs you use and the approved reason codes.
- **App Tracking Transparency (ATT)**: If your app tracks users across other apps/websites, you must use the ATT framework to request permission
- **Required Privacy Manifest APIs include**: File timestamp APIs, System boot time APIs, Disk space APIs, Active keyboard APIs, User defaults APIs

## Age Rating

- Complete the questionnaire in App Store Connect
- Covers: violence, sexual content, profanity, drugs, gambling, horror, etc.
- **Updated January 2026**: Must provide updated responses by the deadline to avoid submission interruption

## Review Guidelines — Key Points

Apple's review guidelines are organized into five sections:

1. **Safety**: No objectionable content, user-generated content must be moderated, apps must have a mechanism for reporting offensive content
2. **Performance**: Must be complete (no betas), stable, accurate descriptions, hardware compatibility declared
3. **Business**: Clear pricing, subscriptions must include terms, in-app purchases use Apple's IAP system (with some exceptions for "reader" apps)
4. **Design**: Must feel native to the platform, follow Human Interface Guidelines, no web app wrappers that add no native value
5. **Legal**: Must comply with all local laws, privacy requirements, intellectual property rights

### Common Apple Rejection Reasons
- Crasher or bug during review
- Incomplete information (missing demo login, broken links)
- Privacy policy missing or inaccessible
- Guideline 4.3 (Spam) — app too similar to existing apps
- Guideline 2.1 (Performance) — app is a simple website wrapper
- Privacy manifest missing or incomplete
- In-app purchase issues (not using Apple IAP where required)
- Metadata mismatch (screenshots don't match app, description is misleading)

## TestFlight (Beta Testing)

- Upload to App Store Connect, select "TestFlight" tab
- **Internal testing**: Up to 100 testers from your team, no review needed
- **External testing**: Up to 10,000 testers, requires Beta App Review
- Builds expire after 90 days
- Useful for getting feedback before submitting for full review

## Submission Process

1. Archive your app in Xcode (Product → Archive)
2. Upload to App Store Connect (from Organizer window or Transporter app)
3. In App Store Connect, select the build for your app version
4. Complete all required metadata
5. Submit for Review
6. Monitor status in App Store Connect (Waiting for Review → In Review → Ready for Sale)

## Post-Approval

- **Phased Release**: Option to release to 1%, 2%, 5%, 10%, 20%, 50%, 100% over 7 days
- **Manual Release**: Hold until you click "Release This Version"
- **Immediate**: Available as soon as approved
- **App Analytics**: Available in App Store Connect after launch
