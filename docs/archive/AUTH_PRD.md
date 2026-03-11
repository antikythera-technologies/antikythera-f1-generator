# Authentication PRD - F1 Mission Control

## Overview

Add authentication to the F1 Mission Control dashboard to protect access and enable user-specific features.

## Goals

1. Protect all dashboard routes behind authentication
2. Support multiple authentication methods (Google, GitHub, Email)
3. Provide seamless login experience
4. Enable future user-specific features (preferences, saved views)

## Technical Stack

- **Framework**: Next.js (App Router)
- **Auth Library**: NextAuth.js v5 (Auth.js)
- **Session Storage**: JWT (default) or Database sessions
- **Database**: PostgreSQL (existing)

## Authentication Methods

| Method | Priority | Provider |
|--------|----------|----------|
| Google OAuth | Primary | Google Cloud Console |
| GitHub OAuth | Secondary | GitHub OAuth App |
| Email/Password | Fallback | Credentials provider |

## Implementation Plan

### Phase 1: Setup & Configuration

1. **Install Dependencies**
   ```bash
   npm install next-auth@beta @auth/prisma-adapter
   ```

2. **Environment Variables Required**
   ```env
   # NextAuth
   NEXTAUTH_URL=https://f1.antikythera.co.za
   NEXTAUTH_SECRET=<generate-random-secret>
   
   # Google OAuth
   GOOGLE_CLIENT_ID=<from-google-console>
   GOOGLE_CLIENT_SECRET=<from-google-console>
   
   # GitHub OAuth
   GITHUB_CLIENT_ID=<from-github-settings>
   GITHUB_CLIENT_SECRET=<from-github-settings>
   ```

3. **OAuth App Setup Required**
   
   **Google OAuth**:
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create OAuth 2.0 Client ID
   - Authorized redirect URI: `https://f1.antikythera.co.za/api/auth/callback/google`
   
   **GitHub OAuth**:
   - Go to GitHub Settings > Developer Settings > OAuth Apps
   - Create new OAuth App
   - Authorization callback URL: `https://f1.antikythera.co.za/api/auth/callback/github`

### Phase 2: Auth Configuration

1. **Create `auth.ts`** (root level)
   ```typescript
   import NextAuth from "next-auth"
   import Google from "next-auth/providers/google"
   import GitHub from "next-auth/providers/github"
   import Credentials from "next-auth/providers/credentials"
   
   export const { handlers, signIn, signOut, auth } = NextAuth({
     providers: [
       Google({
         clientId: process.env.GOOGLE_CLIENT_ID,
         clientSecret: process.env.GOOGLE_CLIENT_SECRET,
       }),
       GitHub({
         clientId: process.env.GITHUB_CLIENT_ID,
         clientSecret: process.env.GITHUB_CLIENT_SECRET,
       }),
       Credentials({
         credentials: {
           email: { label: "Email", type: "email" },
           password: { label: "Password", type: "password" }
         },
         authorize: async (credentials) => {
           // Implement email/password validation
         }
       })
     ],
     pages: {
       signIn: "/login",
     },
     callbacks: {
       authorized: async ({ auth }) => {
         return !!auth
       }
     }
   })
   ```

2. **Create API Route** `app/api/auth/[...nextauth]/route.ts`
   ```typescript
   import { handlers } from "@/auth"
   export const { GET, POST } = handlers
   ```

3. **Create Middleware** `middleware.ts`
   ```typescript
   export { auth as middleware } from "@/auth"
   
   export const config = {
     matcher: ["/((?!api|_next/static|_next/image|favicon.ico|login).*)"]
   }
   ```

### Phase 3: UI Components

1. **Login Page** `/app/login/page.tsx`
   - Antikythera F1 branding
   - Three sign-in buttons (Google, GitHub, Email)
   - Dark theme matching dashboard
   - Logo prominently displayed

2. **User Menu Component**
   - Show user avatar/name in header
   - Dropdown with profile and logout options

3. **Session Provider**
   - Wrap app in SessionProvider
   - Pass session to client components

### Phase 4: Database Schema (Optional)

If storing users in database:

```sql
-- Users table
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email VARCHAR(255) UNIQUE NOT NULL,
  name VARCHAR(255),
  image VARCHAR(500),
  password_hash VARCHAR(255), -- For email/password users
  provider VARCHAR(50), -- 'google', 'github', 'credentials'
  provider_id VARCHAR(255),
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Sessions table (if using database sessions)
CREATE TABLE sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id),
  session_token VARCHAR(255) UNIQUE NOT NULL,
  expires TIMESTAMP NOT NULL
);
```

## File Structure

```
app/
├── api/
│   └── auth/
│       └── [...nextauth]/
│           └── route.ts
├── login/
│   └── page.tsx
├── layout.tsx (add SessionProvider)
└── (protected)/
    └── ... (all dashboard routes)
components/
├── auth/
│   ├── login-form.tsx
│   ├── user-menu.tsx
│   └── sign-out-button.tsx
auth.ts
middleware.ts
```

## Security Considerations

1. **CSRF Protection**: Built into NextAuth.js
2. **Session Security**: Use secure, httpOnly cookies
3. **Password Hashing**: bcrypt for email/password users
4. **Rate Limiting**: Implement on login endpoint
5. **Allowed Users**: Consider allowlist for initial rollout

## Allowed Users (Initial)

| Email | Provider | Role |
|-------|----------|------|
| wiankoch@gmail.com | Google | Admin |
| antikythera-agent-zero | GitHub | Admin |

## UI Mockup

```
┌─────────────────────────────────────┐
│                                     │
│        [Antikythera F1 Logo]        │
│                                     │
│     ┌─────────────────────────┐     │
│     │  Sign in with Google    │     │
│     └─────────────────────────┘     │
│     ┌─────────────────────────┐     │
│     │  Sign in with GitHub    │     │
│     └─────────────────────────┘     │
│                                     │
│     ──────── or ────────            │
│                                     │
│     Email: [________________]       │
│     Password: [______________]      │
│     [        Sign In         ]      │
│                                     │
└─────────────────────────────────────┘
```

## Deliverables

1. ✅ This PRD document
2. ⏳ OAuth credentials (need Wian to create)
3. ⏳ Implementation PR

## OAuth Credentials Checklist

- [ ] Google OAuth Client ID and Secret
- [ ] GitHub OAuth Client ID and Secret
- [ ] Generate NEXTAUTH_SECRET: `openssl rand -base64 32`

## Timeline

| Phase | Task | Estimate |
|-------|------|----------|
| 1 | OAuth credentials setup | 15 min (manual) |
| 2 | NextAuth configuration | 30 min |
| 3 | Login page UI | 45 min |
| 4 | Middleware & protection | 15 min |
| 5 | Testing | 30 min |
| **Total** | | **~2.5 hours** |

## Questions for Review

1. Should we restrict to allowlist initially or allow any Google/GitHub user?
2. Do we need email/password auth or just OAuth?
3. Should sessions persist in database or use JWT only?
4. Any additional roles beyond admin?
