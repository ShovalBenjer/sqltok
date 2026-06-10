# Platforms: limits, tone, and credentials

For each platform: the character or format limit, the tone that fits, and the
environment variables `publish.py` reads. The script only attempts platforms
whose variables are set, and only sends with `--confirm`.

## Recommended targets for a developer tool (US and EU technical audience)

1. Hacker News, "Show HN". The highest-leverage channel. Manual submission is best practice, so the skill generates ready-to-paste title and body. Title format: `Show HN: SQLTok, <one concrete line>`. No marketing words.
2. Reddit r/LocalLLaMA, r/MachineLearning, r/dataengineering. Manual or API. Lead with the result and a link. Communities dislike self-promotion that hides the ask, so be plain.
3. X/Twitter. Technical thread, three to six posts. Use Typefully to fan out and schedule.
4. Bluesky and Mastodon. Research and engineering crowd. One clear post with the link.
5. dev.to and Hashnode. Cross-post the blog with a canonical URL pointing back to your own site so search credit stays with you.

## Per-platform reference

| Platform | Limit | Tone | Env vars |
| --- | --- | --- | --- |
| Bluesky | 300 chars | plain, one link | `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD` |
| Mastodon | 500 chars | plain, one link | `MASTODON_BASE_URL`, `MASTODON_TOKEN` |
| dev.to | full article | canonical cross-post | `DEVTO_API_KEY` |
| Typefully (fan-out: X, LinkedIn, Threads) | per-network | thread for X | `TYPEFULLY_API_KEY` |
| Hacker News | title 80 chars | no hype, factual | manual submission |
| Reddit | per-subreddit | plain, link first | manual, or add a Reddit MCP/credentials |

## How to get credentials

- Bluesky: Settings, App Passwords, create one. Handle is your full handle, for example `you.bsky.social`.
- Mastodon: your instance, Preferences, Development, New application, scope `write:statuses`. Copy the access token and set the base URL to your instance origin.
- dev.to: Settings, Extensions, DEV Community API Keys, generate.
- Typefully: Settings, API. One key fans out to X, LinkedIn, Threads, Bluesky, Mastodon, so it is the simplest way to cover many networks at once.
- LinkedIn direct API is restricted. Route LinkedIn through Typefully or a Zapier MCP connector if needed, with the same style guide and linter applied first.

## Note on connecting accounts

This environment cannot hold your logins. Set the variables above in the shell or
in your Claude Code environment, or connect a Zapier or platform MCP server. Once
the credentials are present, the skill drafts, lints, shows you the text, and on
your confirmation publishes.
