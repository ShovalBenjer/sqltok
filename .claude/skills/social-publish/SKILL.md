---
name: social-publish
description: Draft and publish professional posts across social platforms (X/Twitter, Bluesky, Mastodon, Reddit, Hacker News, dev.to, Hashnode) in a strict house style with no em-dashes, no AI-slop, and no "not X but Y" phrasing. Use when the user wants to announce, launch, share, cross-post, or schedule content. Always lint before publishing and default to dry-run.
---

# social-publish

Turn one piece of news into platform-correct posts, written like a competent engineer, then publish only to the platforms the user has credentials for. The writing rules are not optional. The publishing step is outward-facing, so it defaults to a dry run and requires explicit confirmation.

## Workflow

1. Gather the source. Ask for or infer the one thing being shared (a release, a benchmark result, a blog post URL, a feature). Get the canonical link and one concrete number if there is one.
2. Draft per platform. Write a separate draft for each target platform, following `style_guide.md` and the per-platform limits in `platforms.md`. Lead with the result. One idea per sentence.
3. Lint every draft. Run `scripts/lint_post.py` on each draft. It fails on em-dashes, AI-slop phrases, "not X but Y" constructions, emoji, and exclamation overuse. Fix every finding. Do not publish a draft that fails the linter.
4. Show the user. Print the final drafts in full and the list of platforms that have credentials configured. Ask for confirmation.
5. Publish on confirmation. Run `scripts/publish.py` with `--confirm` only after the user approves. Without `--confirm` it prints exactly what it would send and exits.

## Writing rules (summary, full version in style_guide.md)

- No em-dashes or en-dashes used as punctuation. Use a period or a comma.
- No "not X but Y", "not just X, it is Y", "it is not about X, it is about Y", "not only ... but also". State the thing directly.
- No AI-slop vocabulary: delve, leverage, seamless, robust, powerful, revolutionary, game-changer, unlock, supercharge, tapestry, testament, realm, landscape, dive in, elevate.
- No hype openers ("In today's fast-paced world", "Ever wondered") and no empty closers ("The possibilities are endless").
- No emoji. No hashtag spam. At most one hashtag where the platform expects it.
- Active voice, short sentences, concrete nouns and numbers. Write what it does, not how amazing it is.

## Publishing

`scripts/publish.py` posts only to platforms whose credentials are present in the environment. It uses the standard library, so it needs no extra installs. Supported now: Bluesky, Mastodon, dev.to, and Typefully (a fan-out draft tool that covers X, LinkedIn, Threads, and more). Hacker News and Reddit submissions are generated as ready-to-paste text, since their best practice is a manual human submission.

```bash
# Dry run: prints exactly what would be sent, sends nothing.
python scripts/publish.py --file drafts/bluesky.txt --platform bluesky

# Real post, only after the user has approved the exact text.
python scripts/publish.py --file drafts/bluesky.txt --platform bluesky --confirm
```

See `platforms.md` for the env vars each platform needs and how to get them. If a Zapier or platform-specific MCP server is connected in the session, prefer that for platforms not covered by the script (for example LinkedIn), but apply the same style guide and linter first.

## Guardrails

- Never publish without an explicit user yes on the exact final text.
- Never invent a metric. If there is no number, do not imply one.
- Treat every external link as something the user must see before it goes out.
- One account per platform per run unless told otherwise.
