# SQLTok runbook

The code is complete for v0.1. The steps below need a machine with a local model
or your own accounts, so they are yours to run. Each is copy-paste mechanical.

## 1. Execution-accuracy benchmark (free, no API key)

Needs a machine with Ollama installed. This produces the one remaining number.

```bash
# once
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5-coder:7b

# from the repo
bash benchmarks/download.sh
python benchmarks/run_bird.py --provider ollama --model qwen2.5-coder:7b \
  --questions benchmarks/data/minidev/MINIDEV/mini_dev_sqlite.json \
  --db-root  benchmarks/data/minidev/MINIDEV/dev_databases \
  --budgets 1000 2000 4000

# score with the official BIRD script (see benchmarks/third_party/bird_eval/README.md),
# then paste the accuracy into benchmarks/RESULTS.md and the README table.
```

A `--limit 20` pass first is a good smoke check. Responses are cached, so a full
rerun is free.

## 2. Publish to PyPI

One-time setup, then a release publishes automatically.

1. On https://pypi.org, add a pending trusted publisher for the project:
   owner `ShovalBenjer`, repository `sqltok`, workflow `publish.yml`.
2. Create the release on GitHub: Releases, Draft a new release, tag `v0.1.0`
   targeting `main`, paste the CHANGELOG, Publish. Publishing triggers
   `.github/workflows/publish.yml`, which builds and uploads the wheel.

Manual alternative, if you prefer a token over trusted publishing:

```bash
python -m pip install build twine
python -m build
twine upload dist/*
```

## 3. Turn on the docs site

Repo Settings, Pages, Source: Deploy from a branch, Branch: `gh-pages`. The
`.github/workflows/site.yml` workflow renders the Quarto site and pushes to
`gh-pages` on every push to `main`. The site lands at
`https://shovalbenjer.github.io/sqltok/`.

## 4. Social posting

Set credentials as environment secrets (never in the repo or chat), then post
through the skill. Bluesky is the fastest to set up.

```bash
# after setting BLUESKY_HANDLE and BLUESKY_APP_PASSWORD in the environment
python .claude/skills/social-publish/scripts/publish.py \
  --platform bluesky --file .claude/skills/social-publish/examples/bluesky.txt
# review the dry-run output, then add --confirm to actually post
```

Or run the GitHub Actions button: Actions, Social post, Run workflow, pick the
platform and draft, leave confirm false for a dry run. Secrets go in repo
Settings, Secrets and variables, Actions.

## 5. matchiq

To give another repo the same posting setup, copy
`.claude/skills/social-publish/` and `.github/workflows/social-post.yml` into it
and add the same secrets in that repo's Actions settings.
