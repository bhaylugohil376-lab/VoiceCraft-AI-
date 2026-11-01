# VoiceCraft AI

VoiceCraft AI is a web-based voice studio project.

## Project status and provider setup

The repository contains the frontend pages, server API routes, and Supabase SQL setup files. A successful syntax check or GitHub Pages deployment does **not** prove that live provider integrations are configured or working.

Before using provider-backed features, configure the required server-side environment variables from `.env.example`, deploy the server/API runtime, and test each provider with valid credentials. Never place private API keys in browser-side JavaScript or commit them to this repository.

Some integrations are scaffolds/placeholders until their provider URL, credentials, account permissions, and server deployment are configured. In particular, Music, Sound Effects, and Dubbing require their respective provider configuration. Live API checks are not performed by the repository's static validation scripts and do not prove provider credentials are valid.

## Local checks

- `npm install`
- `npm run check` — JavaScript syntax validation.
- `npm run check:integrations` — static integration-contract checks.
- `npm test` — runs both checks.

## Hosting

GitHub Pages can host the static frontend only. Server API routes that require Node.js, environment variables, authentication, or provider credentials need a compatible backend host; GitHub Pages does not execute the Node.js server.
