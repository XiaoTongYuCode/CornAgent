# CornAgent authentication screen / Attio reference

Reference: https://app.attio.com/auth/sign-in, inspected 2026-09-09 through Chrome computed styles and mobile screenshot.
Scope: adapt the existing functional CornAgent login/registration, retaining its brand and authentication methods. No Google OAuth or Attio legal claims.

## Measured reference
- White full viewport, Inter typography, foreground #101112.
- Page flex column, padding 32px 0 24px, 24px gap; logo height 24px, centered.
- Middle region flex:1, centered both axes. Form group width 360px (364px including 2px outer padding).
- At 2560x1262: logo y32; group x1100 y494.5 width360 height235; footer starts y1168.
- At 390x844: group x15 y285.5 width360 height235. No horizontal overflow.
- Heading 24px/28px weight600, centered; 32px gap to alternate login button.
- Alternate login button height40 radius10 white, inset transparent border, shadow 0 0 2px rgba(28,40,64,.18), 0 1px 3px rgba(0,0,0,.04).
- Alternate button to divider 24px; divider 1px neutral line; divider to form ~32px.
- Email input wrapper height34, 14px/20px weight500, radius8, horizontal padding8/10, icon16 and gap6. Focus inset 1px #266df0.
- Main button height32 radius9, #266df0 white label, font14/20 weight500; 12px gap from input. Color/shadow transition200ms.
- Footer helper max-width360, centered 12px/16px rgba(0,0,0,.63); metadata row gap20 margin-top20, 12px/16px.

## CornAgent structure / interactions
.auth-page > .auth-brand (CornAgent SVG 24px high), .auth-main > .auth-card, .auth-footer.
.auth-card contains h1, .auth-passkey (real Passkey), .auth-divider, form, .auth-method-switch text button, inline alert.
Form email first; Continue requests email code. Challenge state uses same shell with verification title, email summary/change action, code input, optional password setup, resend action. Password mode uses same email and password fields. Retain API contracts, busy/error handling, i18n, expiry and logout.
Use .auth-input wrapping icon and input; labels .auth-field; labels' text .sr-only for email/code/password. .auth-primary main submit. .auth-secondary-actions flex row. .auth-text-button for link-like buttons.
Footer uses actual CornAgent first-verification registration explanation, copyright brand, GitHub and language toggle; no invented privacy/legal links.
Keep .auth-account styling scoped and unchanged.
Responsive width min(360px,100%), page horizontal padding16px on narrow widths; no clipped forms at short heights, allow vertical scrolling. Light login canvas intentional irrespective of chat theme.
