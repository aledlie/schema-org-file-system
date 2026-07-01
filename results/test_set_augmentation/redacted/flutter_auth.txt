# Authentication Data Flow

## Overview

The authentication system uses a **mode-driven approach** with Dart enums and extensions to maintain a single source of truth for auth-related values (routes, text, analytics event names). This document describes the data flow, DRY principles applied, and integration points.

---

## Core Components

### 1. AuthMode Enum

**Location:** `lib/pages/auth_page.dart:14`

```dart
enum AuthMode { signUp, signIn }
```

Two distinct authentication modes:
- `AuthMode.signUp` — User registration flow
- `AuthMode.signIn` — User login flow

### 2. AuthModeX Extension

**Location:** `lib/pages/auth_page.dart:16–37`

Centralizes all AuthMode-dependent values to eliminate duplicated conditionals across the codebase.

```dart
extension AuthModeX on AuthMode {
  String get routePath => this == AuthMode.signUp ? Routes.signup : Routes.login;
  String get title => this == AuthMode.signUp ? 'Create Account' : 'Sign In';
  String get buttonText => this == AuthMode.signUp ? 'Sign Up' : 'Sign In';
  String get pageViewName => this == AuthMode.signUp ? 'auth_signup' : 'auth_signin';
  String get pageSubtitle => this == AuthMode.signUp
      ? 'Get your API key to access the Integrity API'
      : 'Access your account';
  String get toggleModePrompt => this == AuthMode.signUp
      ? "Already have an account? Sign in"
      : "Don't have an account? Sign up";
}
```

**Benefits:**
- Single definition: each value is defined once per mode
- Type-safe: Dart compiler ensures all cases are handled
- Maintainability: update text/routes in one place, changes propagate everywhere
- Reduces cognitive load: intent is clear (`_mode.title` vs `_mode == AuthMode.signUp ? 'Create Account' : 'Sign In'`)

### 3. Routes Constants

**Location:** `lib/config/content/constants.dart:95–110`

```dart
abstract final class Routes {
  static const String home = '/';
  static const String login = '/login';
  static const String signup = '/signup';
  static const String provision = '/provision';
  // ... other routes
}
```

**Key changes (as of latest refactor):**
- `/login` — formerly `/signin`; primary sign-in route
- `/signup` — user registration route

### 4. ProvisioningService

**Location:** `lib/services/provisioning_service.dart`

Handles communication with Auth0 and the provisioning worker.

**Auth flows:**
- `signUp(email, password, name?)` → Creates Auth0 user, returns JWT
- `signIn(email, password)` → Returns JWT for existing user

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                      User navigates to /login                    │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  GoRouter matches /login → creates AuthPage(mode: AuthMode.signIn)
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│              _AuthPageState initializes                          │
│  • _mode = AuthMode.signIn                                       │
│  • didChangeDependencies fires                                   │
│    AnalyticsService.trackPageView(_mode.pageViewName)           │
│    → 'auth_signin'                                               │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│         Render AuthPage UI using AuthModeX getters               │
│  • Page title: _mode.title                                       │
│    → 'Sign In'                                                   │
│  • Submit button: _mode.buttonText                               │
│    → 'Sign In'                                                   │
│  • Toggle link: _mode.toggleModePrompt                           │
│    → "Don't have an account? Sign up"                            │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│         User enters email + password, submits form               │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  _submit() → ProvisioningService.signIn(email, password)        │
│  • POST to sender-worker /signin                                │
│  • sender-worker exchanges (email, password) for JWT            │
│    via Auth0 Resource Owner Password Credentials grant          │
└────────────────────┬────────────────────────────────────────────┘
                     │
             ┌───────┴───────┐
             │               │
        Success          Error
             │               │
             ▼               ▼
     ┌──────────────┐  ┌──────────────┐
     │  AuthSuccess │  │  AuthError   │
     │  jwt: ...    │  │  message: .. │
     │  email: ...  │  └──────────────┘
     └──────┬───────┘        │
            │                ▼
            │        Show error alert
            │        (Alert widget)
            │
            ▼
    context.go('/provision', extra: AuthSuccess)
    ↓
    ProvisionPage displays dashboard/provisioning UI
    (requires valid JWT to proceed)
```

### /signup Flow

```
┌─────────────────────────────────────────────────────────────────┐
│              User navigates to /signup?tier=growth               │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  GoRouter matches /signup → creates SignupPage(tier: 'growth')   │
│  (SignupPage may redirect to AuthPage with AuthMode.signUp)     │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│              _AuthPageState initializes                          │
│  • _mode = AuthMode.signUp                                       │
│  • didChangeDependencies fires                                   │
│    AnalyticsService.trackPageView(_mode.pageViewName)           │
│    → 'auth_signup'                                               │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│         Render AuthPage UI using AuthModeX getters               │
│  • Page title: _mode.title                                       │
│    → 'Create Account'                                            │
│  • Submit button: _mode.buttonText                               │
│    → 'Sign Up'                                                   │
│  • Toggle link: _mode.toggleModePrompt                           │
│    → "Already have an account? Sign in"                          │
│  • Extra field: password confirmation (signUp-only)             │
│    Validation: _confirmPassword == _password                    │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  User enters email + password + confirm password, submits form   │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  _submit() → ProvisioningService.signUp(email, password, name?) │
│                                                                  │
│  Sender-worker executes (in order):                             │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ 1. M2M Token Exchange (client_credentials grant)          │ │
│  │    POST /oauth/token                                      │ │
│  │    Using: AUTHO_CLI_ID + AUTHO_CLI_SECRET                │ │
│  │    Returns: mgmtToken (for Management API)                │ │
│  └───────────────────────────────────────────────────────────┘ │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ 2. Create Auth0 User (Management API)                     │ │
│  │    POST /api/v2/users                                     │ │
│  │    Auth: Bearer mgmtToken                                 │ │
│  │    Payload: { email, password, connection, email_verified}
│  │    Returns: { user_id: "auth0|..." }                      │ │
│  └───────────────────────────────────────────────────────────┘ │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ 3. ROPC User Sign-In (password grant)                     │ │
│  │    POST /oauth/token                                      │ │
│  │    Grant: password (Resource Owner Password Credentials)  │ │
│  │    Using: AUTH0_CLIENT_ID + AUTH0_CLIENT_SECRET           │ │
│  │    Payload: { username, password, audience, scope }       │ │
│  │    Returns: { access_token (JWT), token_type: "Bearer" }  │ │
│  └───────────────────────────────────────────────────────────┘ │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ 4. Create Supabase User + Personal Org                    │ │
│  │    POST /rest/v1/organizations                            │ │
│  │    POST /rest/v1/users                                    │ │
│  │    POST /rest/v1/organization_memberships                 │ │
│  │    (using SUPABASE_SERVICE_ROLE_KEY)                      │ │
│  │    Links auth0_id ↔ supabase user_id                      │ │
│  └───────────────────────────────────────────────────────────┘ │
└────────────────────┬────────────────────────────────────────────┘
                     │
             ┌───────┴────────────────┐
             │                        │
        Success                  Error
             │                        │
             ▼                        ▼
     ┌──────────────────┐    ┌──────────────────┐
     │   AuthSuccess    │    │   AuthError      │
     │  jwt: JWT        │    │  message: "user  │
     │  email: user@... │    │   already        │
     │  auth0Sub: ..    │    │   exists" | ...  │
     └────────┬─────────┘    └────────┬─────────┘
              │                       │
              │                       ▼
              │            Show error alert
              │            (Alert widget)
              │
              │            Auto-redirect?
              │            if (error.contains('already exists'))
              │              context.go('/login')
              │
              ▼
     context.go('/provision', extra: AuthSuccess)
     ↓
     ProvisionPage displays provisioning UI with:
     • API key generation form (tier: growth)
     • Organization setup
     (requires valid JWT + auth0Sub)
```

---

## AuthMode Usage in Code

### Route Selection

```dart
// lib/routing/app_router.dart (line 169)
GoRoute(
  path: '/login',
  builder: (context, state) => AuthPage(
    mode: AuthMode.signIn,
    onBack: _goHome(context),
  ),
),

GoRoute(
  path: '/signup',
  builder: (context, state) => SignupPage(
    tier: state.uri.queryParameters['tier'] ?? 'starter',
    onBack: _goHome(context),
  ),
),
```

### Test Integration

```dart
// test/pages/auth_page_test.dart (line 60)
GoRouter makeAuthRouter(AuthMode mode) => GoRouter(
  initialLocation: mode.routePath,  // Resolves to Routes.signup or Routes.login
  routes: [
    GoRoute(path: Routes.signup, builder: (_, __) => const AuthPage(mode: AuthMode.signUp)),
    GoRoute(path: Routes.login, builder: (_, __) => const AuthPage(mode: AuthMode.signIn)),
    GoRoute(path: Routes.provision, builder: (_, __) => const Scaffold(...)),
  ],
);
```

### Analytics Tracking

```dart
// lib/pages/auth_page.dart (line 78)
if (!_pageViewTracked) {
  _pageViewTracked = true;
  AnalyticsService.trackPageView(_mode.pageViewName);
  // Resolves to 'auth_signup' or 'auth_signin'
}
```

---

## Shared Validation & Constants

To maintain a single source of truth across auth flows (AuthPage and SignupPage), the following shared components are reused:

### Email Validation

**Location:** `lib/services/contact_service.dart`

```dart
static bool isValidEmail(String email) {
  return RegExp(r'^[^\s@]+@[^\s@]+\.[^\s@]+$').hasMatch(email);
}
```

**Usage:**
- `lib/pages/auth_page.dart` — form validation (both signUp and signIn)
- `lib/pages/signup_page.dart` — form validation (line 352)

**Benefit:** Email validation is consistent across all auth forms; single point of update.

### Password Policy

**Location:** `lib/utils/security_utils.dart`

```dart
abstract final class PasswordPolicy {
  static const int minLength = 8;
  static const int maxLength = 128;
}
```

**Usage:**
- `lib/pages/auth_page.dart` — validates password length (both signUp and signIn)
- `lib/pages/signup_page.dart` — validates password length (line 359)
- Signup form error message: `'Password must be at least ${PasswordPolicy.minLength} characters'`

**Benefit:** Password constraints centralized; enforced consistently across all auth flows.

### Routes Constants

**Location:** `lib/config/content/constants.dart` (lines 97–105)

```dart
abstract final class Routes {
  static const String home = '/';
  static const String login = '/login';
  static const String signup = '/signup';
  static const String provision = '/provision';
  static const String checkout = '/checkout';
  // ... other routes
}
```

**Usage:**
- `lib/routing/app_router.dart` — route definitions
- `test/pages/auth_page_test.dart` — test router initialization (line 60)
- `lib/pages/signup_page.dart` — post-signup routing (line 404–409)

**Benefit:** Routes hardcoded in one place; refactoring route paths updates all references automatically.

### Signup Post-Success Routing

**Location:** `lib/pages/signup_page.dart` (lines 403–410)

```dart
/// Route to appropriate page based on tier after successful signup.
void _routeAfterSignup(AuthSuccess result) {
  final tierLower = widget.tier.toLowerCase();
  if (tierLower == 'growth' || tierLower == 'enterprise') {
    context.go(Routes.checkout, extra: CheckoutArgs(email: result.email, tier: widget.tier));
  } else {
    context.go(Routes.provision, extra: result);
  }
}
```

**Logic:**
- `growth` or `enterprise` tier → Redirect to Stripe checkout
- `starter` tier → Redirect to provisioning page (API key generation)

**Benefit:** Tier routing logic isolated in single method; easy to add new tier handling.

---

## Auth0 Integration

### M2M (Machine-to-Machine) for User Creation

**Sender Worker** (`workers/sender-worker/src`):
- Requires `AUTHO_CLI_ID`, `AUTHO_CLI_SECRET`, `AUTHO_CLI_AUDIENCE`
- Uses **client_credentials grant** to obtain management tokens
- Called during `/signup` to create users in Auth0

### ROPC (Resource Owner Password Credentials) for User Sign-In

**Sender Worker** (`workers/sender-worker/src`):
- Uses `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, `AUTH0_AUDIENCE`
- Exchanges (email, password) for JWT via **password grant**
- Called during `/signin` and immediately after `/signup`

### Key Environment Variables

| Variable | Purpose | Grant Type |
|----------|---------|-----------|
| `AUTH0_DOMAIN` | Auth0 tenant | Both |
| `AUTH0_CLIENT_ID` | App client ID | ROPC (password) |
| `AUTH0_CLIENT_SECRET` | App client secret | ROPC (password) |
| `AUTH0_AUDIENCE` | API audience | Both |
| `AUTHO_CLI_ID` | CLI app client ID | M2M (client_credentials) |
| `AUTHO_CLI_SECRET` | CLI app secret | M2M (client_credentials) |
| `AUTHO_CLI_AUDIENCE` | CLI API audience | M2M (client_credentials) |

---

## Error Handling

### RequestFailurePage Auto-Redirect

If signup returns "user already exists" error, the app automatically redirects to `/login`:

```dart
// lib/pages/request_failure_page.dart (line 33)
if (error?.contains('already exists') ?? false) {
  context.go('/login');
}
```

### Error Message Display

```dart
// lib/pages/auth_page.dart
if (result is AuthError) {
  setState(() {
    _errorMessage = result.message;
    _isLoading = false;
  });
  Alert.show(context, message: _errorMessage!);
}
```

---

## Mode Toggle Behavior

```dart
// lib/pages/auth_page.dart (line 121)
void _toggleMode() {
  setState(() {
    _mode = _mode == AuthMode.signUp ? AuthMode.signIn : AuthMode.signUp;
    _password = '';         // Clear password
    _confirmPassword = '';  // Clear confirm password
    // Email preserved
  });
}
```

The toggle link swaps modes while preserving the email field (user often wants to switch between signup/signin with same email).

---

## Summary

**DRY patterns applied:**

1. **AuthMode extension** — Centralizes mode-dependent text and routes
   - Single definition: each value defined once per mode
   - Type-safe: Dart compiler ensures all cases handled
   - Used in: AuthPage (form titles, buttons) and tests

2. **Shared validation** — Email and password rules defined once
   - `ContactService.isValidEmail()` — reused in AuthPage and SignupPage
   - `PasswordPolicy.minLength/maxLength` — reused in AuthPage and SignupPage
   - Ensures consistent validation across all auth flows

3. **Routes constants** — All auth routes defined in one place
   - `Routes.login`, `Routes.signup`, `Routes.provision`, `Routes.checkout`
   - Eliminates hardcoded path strings
   - Single point of update for route refactoring

4. **Signup routing logic** — Tier-based redirect encapsulated
   - `_routeAfterSignup()` method centralizes post-signup routing
   - Handles: starter → `/provision`, growth/enterprise → `/checkout`
   - Easy to extend for new tiers

**Key files:**
- `lib/pages/auth_page.dart` — AuthMode enum + extension, AuthPage widget, form validation
- `lib/pages/signup_page.dart` — SignupPage widget, tier-based routing logic
- `lib/config/content/constants.dart` — Routes constants
- `lib/utils/security_utils.dart` — PasswordPolicy
- `lib/services/contact_service.dart` — Email validation
- `lib/services/provisioning_service.dart` — Auth0 integration
- `lib/routing/app_router.dart` — Route definitions
- `workers/sender-worker/src` — M2M + ROPC implementations
