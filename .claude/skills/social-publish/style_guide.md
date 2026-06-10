# House style for public posts

Write like an engineer who respects the reader's time. The goal is that nobody can tell a machine helped. Every rule below is enforceable, and most are checked by `scripts/lint_post.py`.

## Hard bans

These fail the linter. Do not ship a post that contains them.

1. Em-dashes and en-dashes used as punctuation (the characters U+2014 and U+2013). Use a period, a comma, or a colon.
2. The "not X but Y" family. All of these are banned:
   - "not just X, it is Y"
   - "it is not about X, it is about Y"
   - "not only X but also Y"
   - "X is not just A, it is B"
   These are the single clearest tell of generated text. State the claim once, directly.
3. Emoji and decorative symbols.
4. More than one exclamation mark in a post, and never two in a row.
5. AI-slop vocabulary: delve, leverage, seamless, seamlessly, robust, powerful, revolutionary, game-changer, game changer, unlock, unlocks, supercharge, tapestry, testament, realm, landscape, dive in, deep dive, elevate, harness, embark, navigate the, in the world of, when it comes to, at the end of the day, needle-moving, paradigm.

## Strong discouragements

These are not auto-failed but should be avoided.

- Hype openers: "In today's fast-paced world", "Ever wondered", "Picture this", "Let me tell you".
- Empty closers: "The possibilities are endless", "The future is bright", "Watch this space", "Stay tuned".
- Announcement throat-clearing: "I am thrilled to announce", "Excited to share". Just share it.
- Triadic filler: long lists of three adjectives. One precise adjective beats three vague ones.
- Vague scale words: "massive", "huge", "incredible", "insane". Use a number instead.
- Hashtag spam. At most one hashtag, and only where the platform expects it.

## Positive rules

- Lead with the result or the concrete thing. The first sentence should carry the news.
- One idea per sentence. Short sentences. Active voice.
- Prefer concrete nouns and verbs. Name the tool, the number, the benchmark.
- If you have a number, use it early. If you do not, do not imply one.
- Link once, clearly. Say what is on the other side of the link.
- Sound like a person. Contractions are fine. Mild understatement reads as confident.

## Before and after

Weak: "We are thrilled to unlock a revolutionary, seamless way to supercharge your Text-to-SQL pipeline. It is not just a tool, it is a paradigm shift."

Strong: "SQLTok trims the schema you send to an LLM for Text-to-SQL. On BIRD mini-dev it cut schema tokens by 57 percent at a 1000-token budget. Open source, pip installable."

Weak: "Diving deep into the world of submodular optimization to elevate retrieval."

Strong: "It picks tables by submodular coverage under a token budget, so the prompt stays small and the selected tables are still joinable."
