# Presentation materials

Materials for introducing `evs-cadsr-mcp` at the
[GSA MCP Server and SI Agent Government Hackathon](https://www.gsa.gov/super-intelligence/si-community-of-practice/events-and-training/mcp-server-and-si-agent-government-hackathon).
They are sized for a 15 to 20 minute slot that includes a live demo.



| File | What it is |
| --- | --- |
| [evs-cadsr-mcp-hackathon-deck.pptx](evs-cadsr-mcp-hackathon-deck.pptx) | The slide deck: 16 core slides and 6 backup slides, with speaker notes on every slide |
| [demo-script.md](demo-script.md) | The live demo walk-through in VS Code with GitHub Copilot: setup, eight demos with prompts, expected results and fallbacks |
| [presenter-notes.md](presenter-notes.md) | Timing for 20 and 15 minute versions, talking points for each slide, expected questions, the judging-criteria map, a fact sheet with sources, and a glossary |



## Deck outline

| # | Slide | Section |
| --- | --- | --- |
| 1 | Ask the NCI Thesaurus in plain language, and get codes you can cite | Opening |
| 2 | NCIt: NCI's shared cancer vocabulary | Why it matters |
| 3 | Goal: EVS content for every researcher | Why it matters |
| 4 | Why finding the right term is hard | Why it matters |
| 5 | Agents search; the server keeps them honest | Why it matters |
| 6 | Under the hood: the EVS REST API | Data sources |
| 7 | caDSR: the companion data element registry (out of demo scope) | Data sources |
| 8 | evs-cadsr-mcp at a glance | The server |
| 9 | 21 EVS tools, grouped by the job to be done | The server |
| 10 | Every answer carries its receipts | The server |
| 11 | Nine workflows, run against live EVS | Use cases and demo |
| 12 | Live demo in VS Code with Copilot | Use cases and demo |
| 13 | Evidence: 207 tests and 54 live calls | Evidence and docs |
| 14 | Documentation for every audience | Evidence and docs |
| 15 | Honest limits and next steps | Close |
| 16 | Thank you. Questions? | Close |
| 17–22 | Judging criteria, security posture, known issues, connecting a client, caDSR and mapping tools, anatomy of a tool | Backup |



## Editing the deck

The deck uses PowerPoint layouts (Title, Content, Dark, Backup), so titles sit in placeholders
and the footer and slide numbers come from the layout. The theme, "EVS Hematoxylin", holds the
colors and the two fonts, Cambria for headings and Calibri for text, both standard in Microsoft
Office. Change a color in the theme and the whole deck follows. Charts and code samples use fixed
colors.



## Keeping the numbers current

Every project number in these materials comes from the evaluation run of 23 November 2026
against NCIt release 26.10d ([docs/evaluation/](../evaluation/EVALUATION.md)). NCIt changes
monthly. Before presenting, rehearse with
`uv run --no-sync python scripts/run_use_cases.py --out "$TMPDIR/uc-rehearsal"`. Codes and
relationships should still match; counts may move a little.
