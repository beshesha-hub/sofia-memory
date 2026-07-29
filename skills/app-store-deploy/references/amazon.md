# Amazon Appstore — Detailed Reference

## Account Setup

1. **Create Amazon Developer Account** at developer.amazon.com (free — no registration fee)
2. **Individual vs Company**: Company accounts require business verification documents
3. **Two-factor authentication**: Recommended but not strictly required for account creation
4. **Amazon Developer Agreement**: Must accept before publishing any apps

## Tax & Payments Setup

1. In the Developer Console, go to Settings → Payment Information
2. Add a bank account for receiving revenue (direct deposit)
3. Complete tax interview (IRS tax forms required for all developers, including non-US)
4. Amazon handles tax collection and remittance in many jurisdictions
5. **Important**: Payment threshold is $1 — you get paid once you earn at least $1

## Target Devices

Amazon Appstore serves several device families:

- **Fire Tablets** (Fire OS, based on Android)
- **Fire TV** (Fire TV Stick, Fire TV Cube, smart TVs with Fire TV built in)
- **Echo Show** (limited app support)
- **Fire Phone** (discontinued, but legacy support exists)
- **Windows 11** (via Windows Subsystem for Android — limited, being phased out in 2025-2026)

Fire OS is a fork of Android, so most Android apps work with minimal modification. However, Google Play Services are NOT available — apps depending on them need to use Amazon equivalents or open-source alternatives.

## Current Technical Requirements (2026)

- **APK or AAB**: Amazon accepts both APK and Android App Bundle formats
- **Target API Level**: Amazon recommends targeting the latest Android API but is more lenient than Google Play — apps targeting API level 30+ are generally accepted
- **Fire OS Compatibility**: Test on actual Fire devices or use the Amazon Device Farm. Fire OS may behave differently from stock Android.
- **No Google Play Services**: Replace with Amazon equivalents:
  - Google Maps → Amazon Maps API or OpenStreetMap
  - Firebase Cloud Messaging → Amazon Device Messaging (ADM)
  - Google Sign-In → Login with Amazon (LWA)
  - Google Play Billing → Amazon In-App Purchasing (IAP) API
- **64-bit**: Recommended but not strictly enforced for all app categories yet
- **DRM**: Amazon provides its own DRM system (optional)

## Amazon Device Messaging (ADM)

If your app uses push notifications:

1. Register your app in the Developer Console
2. Obtain API key and OAuth credentials
3. Integrate the ADM SDK (replaces Firebase Cloud Messaging)
4. ADM works only on Fire OS devices — for cross-platform apps, implement both ADM and FCM with a common interface

## App Submission — Creating an App

1. Go to Developer Console → Dashboard → Add New App
2. Select platform: Android or Web App
3. Fill in: App title, Category, Contact information
4. **Important**: You can change between free and paid at any time (unlike Google Play)

## Store Listing Requirements

### Screenshots
- **Minimum**: 3 screenshots
- **Maximum**: 10 screenshots
- **Dimensions**: Between 800x480 and 3840x2160, PNG or JPEG
- **Aspect ratio**: Should match target device aspect ratios
- **Fire TV**: If targeting Fire TV, include landscape screenshots at 1920x1080
- **Fire Tablet**: Include screenshots at tablet resolutions

### Icons
- **Small icon**: 114x114 PNG
- **Large icon**: 512x512 PNG
- No alpha channel required (but transparent backgrounds are supported)

### Promotional Images
- **Promotional image**: 1024x500 PNG or JPEG (similar to Google Play feature graphic)
- **Fire TV banner**: 1920x640 if targeting Fire TV
- Optional but strongly recommended for featured placement

### Video
- **App preview video**: Optional, MP4 or MOV format
- Upload directly (not a URL like Google Play)
- Keep under 5 minutes, ideally 30-90 seconds

### Text
- **App Title**: Up to 250 characters (much more generous than Apple/Google)
- **Short Description**: Up to 1200 characters
- **Long Description**: Up to 4000 characters
- **Keywords**: Separate keyword field — up to 30 keywords, comma-separated
- **Product feature bullets**: Up to 5 bullet points highlighting key features

## Content Rating

1. In the Developer Console, complete the content rating questionnaire
2. Covers: violence, nudity, language, substance use, gambling
3. Amazon assigns its own rating based on your answers
4. **Required before publishing** — apps without ratings won't be approved
5. Less standardized than Apple's or Google's IARC system

## Amazon Appstore Policies — Key Points

- **Content Policy**: No malware, no deceptive behavior, no hate speech, no illegal content
- **Intellectual Property**: Must own or have rights to all content
- **Privacy**: Must have a privacy policy URL if collecting any user data
- **In-App Purchasing**: Must use Amazon IAP API for digital goods (physical goods can use other payment methods)
- **Advertising**: Ads must be appropriate for the content rating and clearly distinguishable from app content
- **Kids Category**: Extra requirements under Amazon's "Made for Kids" program — COPPA compliance required

### Common Amazon Rejection Reasons
- App crashes on Fire devices (tested automatically)
- Missing or broken privacy policy link
- App requires Google Play Services without fallback
- Screenshots don't accurately represent the app
- Description contains misleading claims
- In-app purchases not using Amazon IAP where required
- App doesn't function without internet when it should

## Testing

Amazon provides several testing options:

1. **Live App Testing**: Share pre-release versions with up to 500 testers via email invitation
2. **Amazon Device Farm**: Cloud-based testing on real Fire devices (paid service, but some free tier minutes available)
3. **Fire OS emulator**: Available but limited — physical device testing strongly recommended
4. **Fling**: Side-load APKs to Fire TV for quick testing

### Testing Tips
- Always test on at least one Fire Tablet and one Fire TV (if targeting TV)
- Test with and without WiFi to verify offline behavior
- Verify that no Google Play Services dependencies cause crashes
- Test the IAP flow end-to-end using Amazon's sandbox mode

## Submission Process

1. Build your APK or AAB
2. In Developer Console, go to your app → APK Files tab
3. Upload your binary
4. Complete all metadata tabs (Description, Images, Content Rating, etc.)
5. Set pricing and availability
6. Click "Submit App"
7. **Review timeline**: Typically 1-5 business days, can be longer for new accounts or complex apps
8. **Updates**: Usually reviewed within 1-3 days

## Amazon Appstore Specific Features

### Amazon Underground (Discontinued)
Previously offered "Actually Free" apps with Amazon subsidizing developers. Discontinued, but you may encounter references to it in older documentation.

### Merch by Amazon Integration
If your app relates to merchandise or custom products, there may be integration opportunities.

### Alexa Skills
If your app has voice capabilities, consider creating a companion Alexa Skill. This is a separate submission process but can drive users to your app.

### GameCircle (Deprecated)
Amazon's achievement/leaderboard system. Deprecated in favor of standard Android game frameworks.

## Post-Launch

- **Sales Dashboard**: Monitor downloads, revenue, and in-app purchase metrics
- **Crash Reports**: Available in Developer Console (less detailed than Google's Android Vitals)
- **Customer Reviews**: Respond to reviews from the Developer Console
- **A/B Testing**: Limited compared to Google Play — Amazon has experimented with this but tooling is basic
- **Featured Placement**: Amazon curates featured apps editorially. Quality apps with good Fire device optimization have a better chance.
- **Policy Updates**: Check the Developer Console regularly — Amazon communicates policy changes primarily through email and dashboard notifications

## Key Differences from Google Play

| Feature | Google Play | Amazon Appstore |
|---------|------------|-----------------|
| Registration Fee | $25 one-time | Free |
| Binary Format | AAB required | APK or AAB |
| Google Play Services | Available | NOT available |
| Review Time | 1-3 days | 1-5 days |
| Free→Paid Change | Not allowed | Allowed |
| Push Notifications | FCM | ADM |
| In-App Billing | Google Play Billing | Amazon IAP |
| Device Testing | Firebase Test Lab | Amazon Device Farm |
| Target API Strictness | Very strict | More lenient |
