# Testing ShelfLife

There are three ways to test, from fastest to most realistic:

1. **Automated tests.** Unit and end-to-end tests with simulated services. No keys needed.
2. **Demo mode.** The whole app runs on a built-in simulator with invented companies and prices, so every page and feature can be tried without keys or credits. Results are known in advance, so this guide lists what you should see.
3. **Real services.** The same features against Bifrost and Tavily. Verdicts depend on today's web, so check that each feature works and explains itself, not for exact values.

## 1. Automated tests

```bash
cd backend && uv run pytest
cd frontend && npm run lint && npm test && npm run build
```

The backend has 351 tests, the web app 47. `uv run pytest -m live` also calls the real services and spends a few credits.

**Feature tour.** With the backend running, this runs every feature through the API and prints `ok`, `FAIL` or `SKIP` for each:

```bash
cd backend
uv run python ../scripts/feature_tour.py
```

In demo mode it checks exact results (24 checks pass; the webhook check is skipped unless `ALERT_WEBHOOK_URL` is set). Against real services it only checks that each feature works, needs `--allow-spend`, and runs about eight checks.

## 2. Demo mode

1. In `.env` (in the project root), set `DEMO_MODE=true`. No other setting is needed: keys, models and Bifrost's address are filled in for the simulator.
2. Start the backend, then the web app:

   ```bash
   cd backend && uv run uvicorn app.main:app --port 8000
   cd frontend && npm run dev
   ```

3. Open the web app. The header shows **Demo mode: invented data**.

Demo mode keeps its own history (`backend/.cache/history-demo.sqlite3`), so it never mixes with real checks. Set `DEMO_MODE=false` and restart to go back.

### What to try, page by page

Run the **Check** page steps first: the other pages show what earlier checks found.

#### Check

| Feature | Steps | What you should see |
|---|---|---|
| Live check | Under **Demo scenarios**, click **Cloud recommendation**, then **Check freshness**. | Claims light up one by one. The summary shows 40/100, 6 stale and 2 fresh, and "Checked for: India". |
| Answer guard | Look under the score. | "Advice for apps: hold this answer back. A recommendation in this answer relies on facts that have changed." |
| Why a claim scores 0–5 | Click "Nimbus Cloud's Starter plan costs $20…". | **Freshness 1/100** next to **Evidence strength 82/100 · High**. A near-zero freshness score means strong, recent sources contradict the claim, not that the check failed. **What changed** shows $20 → $28. |
| Independent sources | Same claim, **Evidence**. | "4 sources, 3 independent"; one source says "Same site or story as another source, so it counts once". |
| Hidden assumptions (#2) | Click "Nimbus Cloud's Starter plan allows at least 10 seats". | Labelled **Hidden assumption** and "Answer assumed (never stated)". It's stale: the plan now allows 5 seats. |
| Numerical claim auditor (#8) | Click "For 10 seats, Nimbus Cloud costs $200 a month". | Labelled **Calculation**, with the formula, the stated $200 and the recomputed $280 using today's price. |
| Dependency graph (#11) | Open the **Dependencies** tab. | The recommendation at the top, with the price, calculation and assumption it relies on beneath it, each with its verdict. |
| Decision audit trail (#1) | Click "Nimbus Cloud is the cheapest option…". | Labelled **Recommendation**. "Does this still hold? No", with a **Revised** sentence saying Stratus Cloud is now cheaper, and **Relies on** listing the claims behind it. |
| API breaking change (#6) | Click "nimbus.deploy(app)…". | Labelled **Code**; change type **Deprecated**, with the replacement call. |
| Live availability (#14) and context (#5) | Click "Nimbus Cloud is available in India". | Labelled **Availability**, fresh. The country was added to the Tavily search and to the judging prompt. |
| Corrected answer | Open **Corrected answer**. | Only the stale passages change, with numbered citations. |
| Link rot (#9) | Open **Links**, click **Check links**. | 4 work, 2 deleted, 1 moved, 1 no longer has the quote. |
| Every verdict | Click **Product facts**, then **Check freshness**. | One claim each: stale, uncertain, fresh, unverified, doesn't change, and couldn't check. Advice: show with a warning. |
| Export | Click **Markdown** or **JSON**. | A report with every claim, its kind, verdict, evidence, recalculation and advice. |
| History | Click **Run again**. | **Check history** shows each claim's verdict across both runs. |

#### Compare

Click **Load demo: Three assistants disagree**, then **Compare answers**.

You should see "2 facts where the apps disagree". The Docs assistant is fresh on both (8,000 users, $15), the Sales and Support assistants are stale on both, and each row quotes the source.

#### Dashboard

After a few checks: totals, cost, cache hits, fallbacks and credits; a bar chart of checks per day (hover a bar, or **Show as a table**); verdicts by kind of fact as stacked bars; **Answers held back** listing the cloud answer; claims **Due for a re-check**; and **Recent checks**, each linking back to its result.

#### Claims (provenance passport, #7)

Every checked claim, with an ID like `CLM-F433DE`. Search, filter by verdict, and click one to see its passport: first and last checked, the number of checks, sources, strongest source, and its history. A claim card on the Check page links to its passport.

#### Monitors

| Tab | Steps | What you should see |
|---|---|---|
| Regression tests (#13) | **Fill demo**, **Save test**, then **Run**. | The run fails: "Stale: Acme Cloud costs $10 per month… (now $25 per month)", with a link to the check. **History** lists every run. |
| Link checker (#9) | Pick a saved check, or paste links, then **Check links**. | A table of each link's status. In demo mode, only the invented `.example` sites are visited. |
| Batch check | **Fill demo**, then **Check 3 answers**. Or upload a CSV with an `answer` column (and optionally `question`). | Progress row by row, then each answer's score and verdicts, linking to its check. |
| Context profiles (#4) | Create a profile with a country. On **Check**, open **Context**, choose the profile and run a check. Back here, **Edit** the profile and change the country. | The profile goes to version 2 and says "1 check was made with an older version", with **Re-check now**. The dashboard shows the same under **Context changes**. |

#### Evaluation

Shows "No evaluation results yet" with the four commands, until a labelled evaluation has run with real keys.

#### System

Bifrost status, virtual key, budget, models, fallbacks and providers; Tavily status and credits; the cache plugin with **Enable cache** when it's off; the **Check with ShelfLife** bookmarklet; and the API list with a `curl` example.

To test the bookmarklet, drag **Check with ShelfLife** to the bookmarks bar, select some text on any page, and click the bookmark. ShelfLife opens with the text in the answer box.

#### Webhook alerts

1. Set `ALERT_WEBHOOK_URL=http://127.0.0.1:9000/` in `.env` (in the project root) and restart the backend.
2. Run `python scripts/webhook_echo.py`.
3. Check the cloud answer. The script prints a `stale_claims_found` alert with the stale claims, the advice and the corrected answer.

## 3. Real services

Set `DEMO_MODE=false` and the keys in `.env` as in the README, then restart the backend.

- **Check:** pick an example question and click **Generate with old model**, or paste an answer from any AI app. Open **Context** and pick a country for availability or pricing questions.
- **Compare:** paste answers to the same question from two or three real assistants.
- **Monitors → Regression tests:** save one of the example questions and run it. If a claim is stale, the run fails.
- **Claims**, **Dashboard**, links and batch work the same way as in demo mode.

A real check takes 10–40 seconds, depending on the number of claims and on Tavily's speed.

## Troubleshooting

| Problem | Cause and fix |
|---|---|
| "Tavily is rate-limiting requests" | Too many searches at once. ShelfLife already retries; wait a minute, or lower `TAVILY_CONCURRENCY` in `.env` (default 3). |
| A claim scores 0/100 | Not an error: every counted source contradicts it. Look at **Evidence strength**; if it's high, the claim really is out of date. |
| All verdicts "unverified" | Tavily found nothing usable. Check the Tavily status on **System**, or turn on **Deep verify**. |
| "Bifrost budget has run out" | Raise the virtual key's budget in the Bifrost dashboard. |
| Cache plugin "not known" on System | Set `BIFROST_SETUP_TOKEN` in `.env`. Enabling the cache also needs a vector store in Bifrost's config (see the README). |
| A page says it can't reach the API | Start the backend, and check `NEXT_PUBLIC_API_URL` and `CORS_ORIGINS` if it isn't on port 8000 or the web app isn't on port 3000. |
