# Scoring Rubric v2

The ranking model behind the Job Sniper dashboard. Hard 100-point budget — weights are fixed so dimensions compete honestly instead of everything scoring 9/10.

## Weights

| Dimension | Weight | What it measures |
|---|---|---|
| AI substance | 25 | Is this *actually* AI work, or AI-washed copy? The defining dimension. |
| Salary | 20 | Against your floor and target. |
| Employer tier | 20 | Partnership economics vs. brand vs. agency discount. |
| Work tilt | 15 | Client-facing / strategic vs. internal execution. |
| Location | 10 | Preferred geography vs. elsewhere. |
| Recency | 5 | Fresh postings surface faster. |
| Urgency | 5 | Closing deadlines. |

**Tiebreak:** when two roles land within ~2 points, salary decides. Money talks.

## AI substance (25) — the anti-AI-washing rubric

Score what the role *does*, not what the JD *says*. Anchor on evidence:

- **25** — Multiple responsibilities center on building, evaluating, or directing AI systems. The team mission is AI.
- **~12** — A stated responsibility or team mission directly involves AI products or strategy, but it's one thread among several.
- **0** — "AI" appears once in introductory team boilerplate, or not at all. Buzzword compliance is not substance.

Every part score must carry a one-line justification note. If you can't defend the points in one line, you don't award them.

## Salary (20)

Scored against your floor and target (mine: $140K floor, $150K+ target):

- Full points when the entire disclosed range clears your target.
- Partial when the range merely reaches it.
- No disclosed range: score conservatively — undisclosed comp is information, and it's not in your favor.

## Employer tier (20)

Not prestige for its own sake — it's about economics and trajectory:

- **20** — Partnership-model firms (Big 4 / partnership consultancies): genuine partner-track economics.
- **17** — Finance: banks, PE/VC portfolio ops. Money is the product.
- **14** — Corporate consultancies and Big Tech.
- **11** — Ambiguous: a strong brand's weaker division (e.g. an agency arm of a holding company).
- **8** — Agencies and vendors: great work, structurally capped comp.

Map aliases explicitly (e.g. "Bain Capital" → finance, not consulting) or the tier misfires on unfamiliar names.

## Work tilt (15)

- High: client-facing, strategic, or venture-building work — the stuff that compounds toward partner/principal.
- Mid: mixed product work with some external exposure.
- Low: purely internal product execution.

## Location (10) / Recency (5) / Urgency (5)

- Location: preferred geography full marks, commutable partial, elsewhere low.
- Recency: found in the last 48h scores; decays after.
- Urgency: real closing deadlines score; "no deadline supplied" gets a token floor, not zero — absence of a deadline isn't absence of competition.

## Learning from verdicts

Every `applied` / `dismissed` verdict feeds back as a small learned adjustment per dimension (e.g. "roles without substantive AI work" → −1.5 on AI; "NYC metro roles" → +1.5 on location). Cap the total learned nudge so it tunes the model without hijacking it. This is the model's memory of your *revealed* preferences — it will eventually disagree with your stated ones, and it'll usually be right.

## Calibrating

Score 10 roles by hand first. If everything clusters 70–80, your anchors are too generous — widen the spread until the top of the queue *feels* like the top of the queue. The rubric is a decision tool, not a horoscope: if the ranking doesn't change what you'd do Monday morning, recalibrate.
