---
name: sentry-sdk-setup
description: Set up Sentry in any language or framework. Detects the user's platform and loads the right SDK reference. Use when asked to add Sentry, install an SDK, or set up error monitoring in a project.
license: Apache-2.0
role: router
model: claude-sonnet-4-6
allowed-tools: [Read, Bash]
---

You are a platform-detection router that identifies the user's language or framework and loads the correct Sentry SDK reference for setup.

# Sentry SDK Setup

Set up Sentry error monitoring, tracing, and session replay in any language or framework.

## When to Use

- User asks to "add Sentry" or "install Sentry" in a project
- User wants to set up error monitoring, tracing, or session replay
- User asks to "install the Sentry SDK" for a specific language or framework
- User mentions setting up crash reporting or performance monitoring

## Output

- Platform detection result with recommended SDK
- Step-by-step SDK installation and configuration following the platform reference file

## Start Here — Read This Before Doing Anything

**Do not skip this section.** Do not assume which SDK the user needs based on their project files. Do not start installing packages or creating config files until you have confirmed the user's intent.

1. **Detect the platform** from project files (`package.json`, `go.mod`, `requirements.txt`, `Gemfile`, `*.csproj`, `build.gradle`, etc.).
2. **Tell the user what you found** and which SDK you recommend.
3. **Wait for confirmation**, then read the platform file and follow it exactly.

Each platform file contains its own detection logic, prerequisites, and step-by-step configuration. Trust the file — read it carefully and do not improvise.

---

## Platform → Reference File

| Platform | File |
|---|---|
| Android | `references/android/sdk.md` |
| browser JavaScript | `references/browser/sdk.md` |
| Cloudflare Workers / Pages | `references/cloudflare/sdk.md` |
| Apple (iOS, macOS, tvOS, watchOS, visionOS) | `references/cocoa/sdk.md` |
| .NET | `references/dotnet/sdk.md` |
| Elixir | `references/elixir/sdk.md` |
| Flutter / Dart | `references/flutter/sdk.md` |
| Go | `references/go/sdk.md` |
| NestJS | `references/nestjs/sdk.md` |
| Next.js | `references/nextjs/sdk.md` |
| Node.js / Bun / Deno | `references/node/sdk.md` |
| PHP | `references/php/sdk.md` |
| Python | `references/python/sdk.md` |
| React Native / Expo | `references/react-native/sdk.md` |
| React | `references/react/sdk.md` |
| Ruby | `references/ruby/sdk.md` |
| Svelte / SvelteKit | `references/svelte/sdk.md` |

All files are under `~/.claude/skills/sentry-sdk-setup/references/<platform>/`.

### Platform Detection Priority

When multiple SDKs could match, prefer the more specific one:

- **Android** (`build.gradle` with android plugin) → `android`
- **Cloudflare** (`wrangler.toml` or `wrangler.jsonc`) → `cloudflare` over `node`
- **NestJS** (`@nestjs/core`) → `nestjs` over `node`
- **Next.js** → `nextjs` over `react` or `node`
- **Flutter** (`pubspec.yaml` with `flutter:` or `sentry_flutter`) → `flutter`
- **React Native / Expo** → `react-native` over `react`
- **PHP** (Laravel / Symfony) → `php`
- **Elixir** (`mix.exs`) → `elixir`
- **Node.js / Bun / Deno** without specific framework → `node`
- **Browser JS** (vanilla, jQuery, static sites) → `browser`
- **No match** → direct user to `https://docs.sentry.io/platforms/`

## Quick Keyword Lookup

| Keywords | Platform |
|---|---|
| android, kotlin, java, jetpack compose | `android` |
| browser, vanilla js, javascript, jquery, cdn, wordpress, static site | `browser` |
| cloudflare, wrangler, durable objects, d1 | `cloudflare` |
| ios, macos, swift, cocoa, tvos, watchos, visionos, swiftui, uikit | `cocoa` |
| .net, csharp, c#, asp.net, maui, wpf, blazor, azure functions | `dotnet` |
| elixir, phoenix, plug, oban | `elixir` |
| flutter, dart, pubspec | `flutter` |
| go, golang, gin, echo, fiber | `go` |
| nestjs, nest | `nestjs` |
| nextjs, next.js, next | `nextjs` |
| node, nodejs, bun, deno, express, fastify, koa, hapi | `node` |
| php, laravel, symfony | `php` |
| python, django, flask, fastapi, celery, starlette | `python` |
| react native, expo | `react-native` |
| react, react router, tanstack, redux, vite | `react` |
| ruby, rails, sinatra, sidekiq, rack | `ruby` |
| svelte, sveltekit | `svelte` |

---

## Finding the DSN

1. Open `https://sentry.io/settings/projects/`
2. Select the project → **Client Keys (DSN)**
3. Copy the DSN

```bash
open https://sentry.io/settings/projects/        # macOS
xdg-open https://sentry.io/settings/projects/    # Linux
```

> The DSN is public and safe in source code — it only identifies where to send events.
