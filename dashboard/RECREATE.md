# The Dashboard — Recreation Guide

The scraper in `/scraper` is the sensing layer. This document describes the decision layer that sat on top of it: a private ranked-queue web app ("Job Dashboard") that turned raw postings into a prioritized hunt. The app itself is a hosted fullstack app and can't be exported, so this is a complete spec — hand it to an AI agent (or build it yourself) to recreate it.

## The loop

```
daily cron ──> run.py --sources watchlist --seen seen.json ──> new jobs (JSON)
                                                              │
                                              ingest: fetch full description per job
                                                              │
                                              score each job 0–100 (scoring.md)
                                                              │
                                              ranked queue ──> you work top-down:
                                                               read dossier → set status
                                                               (new / applied / dismissed)
                                                               → log outreach targets
```

A daily run (morning, silent unless something is new/urgent) keeps the queue fresh. You never scroll job boards again — you open the queue.

## Data model

One record per role. Fields that mattered:

| Field | Notes |
|---|---|
| `title`, `company`, `location`, `url` | From the scraper |
| `description` | Full posting text (~2.5k chars), fetched at ingest — scoring needs the whole JD, not a snippet |
| `salaryText`, `rankingSalary` | Parsed range; the ranking number is what the scorer uses |
| `score`, `scoreParts[]` | 0–100 total; each part carries `{key, label, maximum, points, note}` — the note is a human-readable justification, and it's what makes the score trustworthy |
| `status` | `new` → `applied` / `dismissed`; `excluded` with reason for hard no's |
| `resume` | Which of your resumes fits this role + why (see below) |
| `outreachTargets[]` | Networking targets per role (see below) |
| `learnedAdjustment` | Score nudge from your past verdicts (see below) |

## Scoring

Fixed 100-point budget — see [`scoring.md`](scoring.md) for the full rubric:

| Dimension | Weight |
|---|---|
| AI substance | 25 (the defining dimension) |
| Salary | 20 |
| Employer tier | 20 |
| Work tilt | 15 |
| Location | 10 |
| Recency | 5 |
| Urgency (deadline) | 5 |

Two mechanisms kept it honest:

1. **Per-part notes.** Every score part carries a one-line justification ("single mention appears only in introductory team copy" → 0 AI points). If you can't defend the points in one line, you don't award them. This is also what defeats AI-washing in JDs.
2. **Learning from verdicts.** Every applied/dismissed verdict feeds back as a small learned adjustment per dimension (e.g. "roles without substantive AI work" → −1.5 on AI). The model tunes itself to your revealed preferences instead of your stated ones.

Salary acts as a tiebreak within ~2 points — when scores are close, money talks.

## Per-role dossier

Each role gets a dossier view: full description (auto-cleaned — entities resolved, stray HTML stripped, glued section headers split into paragraphs), score breakdown with the justification notes, the `why` summary line, salary, and status controls. This is where you decide: pursue, apply, or dismiss.

## Networking panel

The highest-ROI part. Each role carries a flat list of up to 3 outreach targets:

```
{name, title, selectionReason, status: to-contact → contacted → replied}
```

Plus a one-tap LinkedIn search button (`{Company} {role family} #hiring`) and quick-add. The discipline: warm intros and direct outbound beat inbound applications — the panel exists to make the outbound list unavoidable.

## Resume picker

Two resumes, and the app tells you which one to send per role with a reason:

- **6-YOE, 1 page** — tight recent story (last ~5 years), GTM/launch framing. For product roles where recency beats breadth.
- **Full, 2 pages** — adds early career, advisory work, service-delivery/ops framing. For consulting, partner-track, and senior/breadth roles.

Rule of thumb encoded: ~5 YOE roles get the 1-pager (a 2-pager looks off); 8+ YOE / consulting-breadth roles get the full.

## Rebuild steps

1. Take `/scraper` and build a `sources.json` watchlist of your target companies' career pages and ATS boards.
2. Store results in any database (SQLite is plenty) using the data model above; fetch full descriptions at ingest.
3. Implement the rubric in `scoring.md` — fixed weights, per-part justification notes, learned adjustments from your verdicts.
4. Build the queue UI: ranked list → dossier view → status controls. Add the networking panel and resume picker.
5. Schedule the daily ingest. Silent on success; loud only when something is new, closing, or urgent.

That's the whole system. The scraper finds; the rubric ranks; you hunt.
