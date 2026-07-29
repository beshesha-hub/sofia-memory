# Google Play Store — Detailed Reference

## Account Setup

1. **Create Google Play Developer Account** at play.google.com/console ($25 one-time fee)
2. **Identity Verification**: Google requires identity verification for all developer accounts. New accounts go through a verification process that can take several days.
3. **Developer Profile**: Must be complete and accurate — display name, contact email, website (if applicable)
4. **Organization accounts**: Require a D-U-N-S number and additional business verification
5. **Starting September 2026**: Only apps from verified developers can be installed on Android devices in select countries. Ensure your verification is complete well ahead of this.

## Tax & Payments Setup

1. In Play Console, go to Setup → Payments profile
2. Add a payment method (bank account for receiving revenue)
3. Complete tax information (US tax forms required even for non-US developers)
4. Set up a Merchant account if selling paid apps or in-app items

## Current Technical Requirements (2026)

- **Target API Level**: New apps and updates must target Android 15 (API level 35) or higher
- **Wear OS/Android Automotive/Android TV**: Must target Android 14 (API level 34) or higher
- **Build Format**: Android App Bundle (AAB) required — APK is no longer accepted for new apps on Google Play
- **App Signing**: Google Play App Signing is required for new apps. Google manages your app signing key; you upload with an upload key. This protects against key loss.
- **64-bit**: Required. Apps must include 64-bit libraries.

## App Signing — Step by Step

1. **For new apps**: Google Play App Signing is automatic. Generate an upload key in Android Studio.
2. **Upload key**: This is what you use to sign your AAB before uploading. If compromised, you can reset it through Play Console (unlike the app signing key).
3. **App signing key**: Managed by Google. Cannot be changed after initial upload. This is what signs the APKs delivered to users.
4. **Key export**: You can download your app signing key certificate from Play Console if needed for third-party integrations.

## Play Console — Creating an App

1. Go to Play Console → All apps → Create app
2. Fill in: App name, Default language, App/Game, Free/Paid
3. Accept developer program policies
4. **Important**: Free apps cannot be changed to paid later. Paid apps can be changed to free.

## Store Listing Requirements

### Screenshots
- **Phone**: Minimum 2, maximum 8. Recommended: 4-8
- **Tablet**: Minimum 1 if targeting tablets
- **Dimensions**: Min 320px, max 3840px on any side. Aspect ratio: 16:9 or 9:16
- **Format**: JPEG or 24-bit PNG, no alpha
- **Chromebook/TV/Wear**: Additional screenshots needed if targeting these form factors

### Feature Graphic
- **Required**: 1024 x 500 PNG or JPEG
- Displayed prominently in Play Store — invest time in making it look good
- No alpha, no rounded corners

### Icons
- **High-res icon**: 512 x 512 PNG, 32-bit with alpha
- Must conform to Google's icon design guidelines (adaptive icon)

### Text
- **App Name**: Up to 30 characters
- **Short Description**: Up to 80 characters (critical for ASO)
- **Full Description**: Up to 4000 characters
- **Developer name, email, website**: Required and displayed publicly

### Promotional Video
- YouTube URL only (not a file upload)
- Should be a short demo, not a trailer with irrelevant footage

## Data Safety Section

Mandatory since July 2022 and strictly enforced in 2026:

- Declare all data types collected (name, email, location, files, etc.)
- Indicate whether data is collected, shared with third parties, and whether it's optional
- Declare data handling practices (encryption in transit, deletion mechanism)
- Must have a privacy policy URL
- **Accuracy is critical**: Google may verify your declarations against your app's actual behavior using automated scanning. Inconsistencies can result in suspension.

## Content Rating (IARC)

1. In Play Console, go to Policy → App content → Content ratings
2. Complete the IARC questionnaire — answers about violence, sexuality, language, substance use, gambling, etc.
3. The system generates ratings for multiple regions simultaneously (ESRB, PEGI, etc.)
4. **Required before publishing** — apps without ratings won't be approved
5. Re-complete if app content changes significantly

## Google Play Policies — Key Points

- **Restricted Content**: No malware, deceptive behavior, inappropriate content
- **Privacy**: Must have a privacy policy, must declare data practices accurately
- **Monetization**: Transparent pricing, no deceptive ads, in-app purchases must use Google Play Billing (with some exceptions)
- **Families Policy**: Extra requirements if your app targets children (Teacher Approved program, COPPA compliance)
- **AI-Specific (2026)**: Apps using generative AI must moderate outputs, disclose AI-generated content, and handle user data appropriately

### Common Google Rejection/Suspension Reasons
- Policy violation (deceptive behavior, misleading description)
- Crashes or ANR (Application Not Responding) rates too high
- Missing or inaccurate data safety section
- Inappropriate content rating
- Using deprecated APIs or not meeting target API level
- Permissions requested without clear justification to the user
- In-app purchases not using Play Billing where required

## Testing Tracks

1. **Internal testing**: Up to 100 testers, fastest setup, no review
2. **Closed testing**: Invite-only, up to 2000+ testers, minimal review
3. **Open testing**: Anyone can join, review required, good for large-scale beta
4. **Production**: Full public release

Use testing tracks progressively — internal → closed → open → production.

## Submission Process

1. Build your AAB in Android Studio (Build → Generate Signed Bundle)
2. In Play Console, go to your app → Release → Production (or testing track)
3. Create a new release
4. Upload your AAB
5. Add release notes
6. Review and roll out
7. **First submission review**: Typically 1-3 days for new apps, can be longer for new developer accounts
8. **Updates**: Usually reviewed within hours to 1 day

## Staged Rollout

- Available for production releases
- Start at any percentage (e.g., 5%, 10%)
- Monitor crash reports and ANR rates before increasing
- Can halt rollout if issues found
- Increase to 100% when confident

## Post-Launch

- **Android Vitals**: Monitor crash rate, ANR rate, excessive wake-ups, stuck partial wake locks
- **Pre-launch reports**: Google automatically tests your app on Firebase Test Lab devices
- **Store listing experiments**: A/B test your icon, screenshots, description
- **Ratings & Reviews**: Respond to reviews directly from Play Console
- **Policy updates**: Subscribe to the Google Play Developer newsletter for policy changes
