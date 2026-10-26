---
name: scrape
description: Use when the user wants djinni.co job postings collected or analysed: gives a djinni.co/jobs search URL, asks to scrape or pull jobs from djinni, or asks about salaries, stacks or companies across a djinni search. Runs the bundled polite scraper and reads its Markdown output.
argument-hint: <djinni.co/jobs search URL> [question about the postings]
---

# Scrape djinni

The bundled `djinni-scraper` CLI pages through a djinni.co search, reads every posting from the
page's embedded JSON-LD, and appends it to one Markdown file per search per day.

**djinni IP-blocks aggressive scrapers for a full day.** Every rule below exists to avoid that.

## Run it

1. Get the listing URL from the user: a `https://djinni.co/jobs/?...` search they built on the
   site. Use it exactly as given. Do not build or edit query parameters from a description of
   filters. If there is no URL, ask for one.
2. Run the scraper with the Bash tool and `run_in_background: true`: a full search runs for
   minutes, longer than a foreground call's timeout.

   ```sh
   uvx --no-config --from "${CLAUDE_PLUGIN_ROOT}" djinni-scraper "<URL>" --out-dir ~/djinni-jobs
   ```

   - Keep `--out-dir ~/djinni-jobs` unless the user names another directory. Resume finds the
     earlier file only in the same directory.
   - Add `--max-pages N` or `--max-jobs N` only when the user asks for a smaller run.
   - Never pass a `--delay` below the default 4 seconds, and never run two scrapes at once.
     Several URLs run one after another.
3. When it finishes, read the log output.
   - `Wrote N new postings.` with no warning: done.
   - A line containing `Wait a while and re-run to resume` means djinni throttled or blocked the
     run, whatever the exit code (it is still 0). The preceding line says why (`Blocked by
     djinni`, `Cloudflare challenge`, `Repeated HTTP`, `Unexpected HTTP`, `Giving up after
     retries`). Stop. Tell the user what was saved and that the same command resumes later.
     Do not retry, do not lower the delay, and do not try another URL in this session.
   - `error: ... Use --overwrite or a different --out-dir.`: today's file for this name was made
     by another search or is damaged. Ask the user before adding `--overwrite`: it replaces the
     file.

## Read the output

The file is `~/djinni-jobs/<YYYY-MM-DD>__<host-path-query>.md`. Its header holds `source_url`,
and each posting is a `## Title` section under a `<!-- job-id: N -->` marker, with
`- **Company:**`, `Salary`, `Location/Remote`, `Experience`, `English`, `Domain`, `Posted`,
`URL` and `Scraped-at` lines, then the description.

A full run holds up to 1000 postings, too much for one Read. Answer questions with Grep over the
field lines (`- **Salary:**`, `- **Company:**`) and Read in line ranges for the descriptions you
need. Quote the posting URL for any job you name.
