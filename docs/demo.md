# Demo run-sheet

A three-minute live demo. Button and tab names below are exactly as they appear in the app.

## The night before

1. Re-check the evaluation labels, then run the evaluation again. Use the numbers it writes for the evaluation slide.

   ```bash
   cd backend
   uv run python ../scripts/eval_label.py --labeller "Your Name" --recheck-older-than 1
   uv run python ../scripts/run_eval.py --second-run --update-readme
   ```

2. Check Bifrost. Every line should say `[ok]`, including the cache plugin:

   ```bash
   uv run python ../scripts/bifrost_setup.py
   ```

3. In the Bifrost dashboard, check that the virtual key's budget has room left.
4. Rehearse the whole flow once with a **different** example question from the one you'll demo. If you rehearse with the demo question, its first live run will already be cached, and the before-and-after comparison won't show anything.
5. Record a backup: a screen recording of a good run, plus its **Markdown** and **JSON** exports.

## 30 minutes before

- Start Bifrost, then the backend **without** `--reload`, since checks are kept in memory and a reload would lose them. Then start the web app.
- Open http://localhost:8000/api/health and confirm `"status": "ok"`.
- Open two browser tabs: the web app at http://localhost:3000, and the Bifrost dashboard on the **Providers** page, with **Logs** one click away.
- Make sure **Use Bifrost cache** is on and **Deep verify** is off.
- Zoom the browser to about 110% so the audience can read the text.

## Run of show

| Time | Do | Say |
|---|---|---|
| 0:00 | Show the empty app. | "AI answers state outdated facts with full confidence: old prices, old versions, people who've left their jobs. ShelfLife finds those claims and checks them against the live web." |
| 0:15 | Under **Try an example**, click **AI pricing and leadership**. | "Here's a question about pricing, leadership and versions. We ask an older model to answer it from memory." |
| 0:30 | Click **Check freshness**. | "ShelfLife splits the answer into claims, skips the ones that can't go out of date, and searches Tavily for the rest. Watch them light up as each one is scored." |
| 0:55 | Click a red (stale) claim. Point at **What changed**, then the evidence with dates and quotes, and "N sources, M independent". | "The answer said this; current sources say that, as of this date. Every stance is backed by a quote that really appears in the source, and two sites repeating one story count once." |
| 1:10 | Click **How it was scored**, then a green claim and its **Re-check by** date. | "The score isn't the model's opinion. Code combines each source's authority, its age against how fast this kind of fact changes, and whether sources agree. It even works out when each fresh claim needs checking again." |
| 1:25 | Open the **Corrected answer** tab. Point at the struck-through and new text, then the source list. Click **Markdown**. | "Only the stale claims change, with citations. Everything else stays word for word, and the full report downloads as Markdown or JSON." |
| 1:40 | Scroll to **Run metrics**. Point at the stage table and the virtual key budget line. | "Every LLM call goes through Bifrost. A cheap model extracts claims and a strong one judges evidence. This budget is enforced by Bifrost, not by our code." |
| 1:55 | Click **Run again**. When it finishes, point at the cache hits and the "was" values, then **Check history**. | "Same answer again: Bifrost answers repeat calls from its cache, so cost and time drop. Every check is saved, so each claim has a history." |
| 2:10 | In the Bifrost dashboard, disable the primary provider for the strong model. Back in the app, click **Run without cache**. | "Now the primary provider is down. The cache is off, so every call has to reach a provider." |
| 2:25 | Point at the **Fallback** labels on the claims and **Served by fallback** in the metrics. Open Bifrost's **Logs**. | "The check still finished: Bifrost moved each call to the fallback, and every request is in its logs." |
| 2:40 | Show the evaluation slide, with the numbers from `eval/results.md`. | "We measured it on human-labelled answers: precision, recall and F1 for spotting stale claims, and the false-alarm rate on claims that are still true." |
| 2:55 | Back to the app. | "ShelfLife is a drop-in verification layer for any AI app." |

After the demo, re-enable the primary provider in the Bifrost dashboard.

## If you have two more minutes

Prepare these during rehearsal, so they already have data: a recommendation-style answer checked with a country in **Context**, a comparison of two real assistants' answers to the same question, and one saved regression test.

| Do | Say |
|---|---|
| On the recommendation answer, open **Dependencies**, then click the recommendation. | "Answers don't just state facts, they reason with them. When a price under this advice changed, ShelfLife recomputed the total and re-judged the advice, and it told the app to hold the answer back." |
| Open **Compare**. | "Two assistants, one question, different numbers. Each fact is searched once and both versions are judged against the same sources, so you can see which app is out of date." |
| Open **Claims** and click a claim. | "Every claim gets a passport: when it was verified, by which sources, and its history." |
| Open **Monitors**, run the regression test. | "Teams can re-ask a model their key questions after each model update, and the test fails as soon as an answer goes stale." |
| Open **Dashboard**. | "Across everything checked: what's stale, what's due for a re-check, and what Bifrost and Tavily did." |

## Demo mode as a backup

If the keys, Bifrost or Tavily fail on the day, set `DEMO_MODE=true` in `.env` and restart the backend. Every page works on a built-in simulator with invented companies, and the header says so. Say clearly that it's simulated data; use it to show the features, not results. [testing.md](testing.md) lists what each page shows in demo mode.

## If something goes wrong

| Problem | What to do |
|---|---|
| A check is slow | Talk through the claims that have already arrived. They appear one at a time. |
| No cache hits on **Run again** | The cache plugin isn't on. Skip that step and mention the cache from the metrics panel. |
| No fallback after disabling the provider | Check that **Run without cache** was used and that the right provider is disabled. Otherwise, show the backup recording. |
| "The Bifrost budget for this app has run out" | Raise the budget in the Bifrost dashboard, or turn it into a demo point: Bifrost enforced the limit. |
| The backend won't respond | Use the backup recording and the exported report. |
| "Tavily is rate-limiting requests" | Wait a minute and use **Run again**. Before the demo, keep `TAVILY_CONCURRENCY` at 3 or lower. |

## Recording the video

- Record at 1080p with the browser zoomed to about 110%.
- Follow the run of show above. It fits in about three minutes.
- Cut the waiting time while a check runs, but keep a few seconds of claims lighting up, since that shows it's live.
