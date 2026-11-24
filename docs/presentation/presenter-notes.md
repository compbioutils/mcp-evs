# Presenter notes: evs-cadsr-mcp at the GSA MCP Hackathon

These notes go with [the slide deck](evs-cadsr-mcp-hackathon-deck.pptx) and the
[live demo script](demo-script.md). The same talking points are in the deck's speaker notes,
so you can see them in PowerPoint's Presenter View.

## Contents

1. [Three messages to land](#three-messages-to-land)
2. [Timing plan](#timing-plan)
3. [Slide-by-slide talking points](#slide-by-slide-talking-points)
4. [Questions to expect](#questions-to-expect)
5. [Judging criteria and where the evidence is](#judging-criteria-and-where-the-evidence-is)
6. [Fact sheet: every number in the deck and its source](#fact-sheet-every-number-in-the-deck-and-its-source)
7. [Wording to keep accurate](#wording-to-keep-accurate)
8. [Glossary](#glossary)
9. [Checklist](#checklist)



## Three messages to land

1. **The NCI Thesaurus matters and is hard to search well.** It is NCI's shared vocabulary of
   about 178,000 concepts and it changes monthly. Synonyms, brand names, near-miss results,
   codes from other systems and many-parent hierarchies all trip up keyword search and chatbots.
2. **evs-cadsr-mcp lets any MCP-capable assistant find the right term and prove where it came
   from.** It offers 21 goal-shaped EVS tools, and every answer carries the NCIt release and the
   exact EVS URL. Releases fail closed and errors come with hints.
3. **It is tested, and we say what doesn't work yet.** There are 207 automated tests, nine
   real-world workflows run against live EVS (52 of 54 steps pass), a keyword-search baseline,
   and six findings logged with fixes.



## Timing plan

The core deck is slides 1 to 16. Slides 17 to 22 are backup slides for Q&A.

| Slide | Topic | 20-minute version | 15-minute version |
| --- | --- | --- | --- |
| 1 | Title | 0:30 | 0:20 |
| 2 | NCIt: NCI's shared cancer vocabulary | 1:15 | 1:00 |
| 3 | Goal: EVS content for every researcher | 1:00 | 0:45 |
| 4 | Why finding the right term is hard | 1:15 | 1:15 |
| 5 | Agents search; the server keeps them honest | 1:00 | skip (one sentence at the end of slide 4) |
| 6 | Under the hood: the EVS REST API | 1:00 | 0:45 |
| 7 | caDSR: the companion data element registry | 1:00 | 0:45 |
| 8 | evs-cadsr-mcp at a glance | 1:00 | 0:45 |
| 9 | 21 EVS tools, grouped by the job to be done | 1:00 | 0:30 |
| 10 | Every answer carries its receipts | 1:00 | 0:45 |
| 11 | Nine workflows, run against live EVS | 1:00 | 0:45 |
| 12 | Live demo | 6:00 (demos 1, 2, 3, 4, 6, 8) | 4:30 (demos 1, 2, 3, 4, 8) |
| 13 | Evidence: 207 tests and 54 live calls | 1:00 | 0:45 |
| 14 | Documentation for every audience | 0:45 | 0:20 |
| 15 | Honest limits and next steps | 0:45 | 0:20 |
| 16 | Thank you / questions | 0:15 | 0:15 |
| | **Total** | **about 19:45** | **about 14:45** |

If you run long, the demo is where to cut: drop demo 6, then demo 3. If you run short, add
demo 5 (CDISC) or demo 7 (retired codes) from the demo script.



## Slide-by-slide talking points

### Slide 1: Ask the NCI Thesaurus in plain language, and get codes you can cite

*Time: 0:30*

Introduce yourself and the project in one breath: evs-cadsr-mcp is a read-only MCP server that lets AI assistants search and navigate NCI Enterprise Vocabulary Services (EVS), above all the NCI Thesaurus (NCIt), and cite exactly where each answer came from.

Roadmap: what EVS is and why finding the right term is hard; the two NCI APIs underneath; what we built; nine real workflows; a live demo in VS Code; and our test evidence.

Point at the graphic: it is real data. It is a slice of where "Lung Non-Small Cell Carcinoma" (C2926) sits in NCIt release 26.10d. It has two parents and 16 different paths to the root. That is one reason finding and using the right term is hard.



### Slide 2: NCIt: NCI's shared cancer vocabulary

*Time: 1:15*

EVS is NCI's terminology service. Its core product is the NCI Thesaurus: about 178,000 concepts as of August 2026, more than 400,000 relationships between them, and 550+ subsets (value sets), most of them inside NCIt. It is released monthly, with 500+ new concepts a month, and it is openly licensed (CC BY 4.0). Partners such as FDA and CDISC maintain content in it, which is why NCIt codes show up in submissions, registries and data commons.

Walk the card on the right. It is one concept, Melanoma (C3224), as the live API returns it: 17 synonym entries from 11 sources, 4 definitions, properties such as its ICD-O-3 code and UMLS CUI, relationships to findings (including an exclusion), and maps to ICD-O-3 and GDC. MedDRA maps exist but need a license key. Every one of these facts belongs to a specific monthly release.

Sources: evs.nci.nih.gov; NCI EVS wiki (Shared Terminology Development, Aug 2026; EVS Resources). Concept data: live EVS REST API, NCIt 26.09d and 26.10d.



### Slide 3: Goal: EVS content for every researcher

*Time: 1:00*

Our primary goal is access for the scientific community.

Today there are three ways in. The EVS Explore browser is good for one concept at a time. File downloads (OWL, flat files) suit bulk pipelines. The REST API suits programmers. Each one assumes you already know the terminology well, or can write code.

MCP adds a fourth door: ask in plain language from a tool you already use, such as VS Code with Copilot, Claude, or any MCP client. The assistant calls EVS for you and shows its sources.

The people who benefit are the ones in our use cases: researchers, data managers, registrars, standards analysts, curators and NLP developers.

### Slide 4: Why finding the right term is hard

*Time: 1:15*

Eight things we saw in live EVS results (NCIt 26.10d).

1. Everyday names: "NSCLC" is only a synonym; the preferred name is "Lung Non-Small Cell Carcinoma".
2. One drug, many names, and they land on different concepts: the brand Tagrisso is a synonym of the salt; the code name AZD9291 and the generic name are on the ingredient.
3. Near-misses can mean the opposite: search "EGFR L858R" and result #2 is "EGFR L858R Negative".
4. Short values collide: a contains-search for "F" in CDISC Sex also returns Intersex.
5. Codes from other systems, such as ICD-O "8140/3", are properties, not names, so free-text search fails.
6. Lay and definition-style wording ("blood cancer", "brain tumor") misses keyword search.
7. Many parents: NSCLC has 16 paths to the root.
8. Monthly change: C28327 was retired and merged into C4029, and EVS serves only the 4 most recent releases.

A terminology expert navigates all of this. A chatbot without tools will guess, and a guessed code looks exactly like a real one.



### Slide 5: Agents search; the server keeps them honest

*Time: 1:00*

Our design splits the work. The assistant reads the question, plans and picks tools. The server makes sure what comes back is real, bounded and cited.

Six capabilities map to the eight pitfalls (the numbers refer to the previous slide):

- Exact lookup that says how it matched (code, name or synonym) and returns nothing rather than guess (1, 2, 6).
- Filtered, paged search: exact or fuzzy matching, limited by subset or source (3, 4).
- Concept sets by rule: by property value such as ICD-O or FDA UNII, or by relationship, with the query plan shown (5).
- Hierarchy and relationship tools that flag exclusions instead of following them (7).
- Pinned releases with provenance on every answer, and history for retired codes (8).
- Errors with hints so the agent recovers instead of improvising; truncation is always reported (all).



### Slide 6: Under the hood: the EVS REST API

*Time: 1:00*

Underneath is the EVS REST API (EVSRESTAPI), the same public API that powers the EVS Explore browser. It sits on a triple store with Elasticsearch indexes, so it exposes the full ontology and makes it searchable.

It serves NCIt plus other terminologies, such as the NCI Metathesaurus and CTCAE 5.0 and 6.0. NCIt needs no key; license-gated sources such as MedDRA do.

Crucially, it is release-addressable: you can put the release in the path, for example /concept/ncit_26.10d/C3224.

Six endpoint families matter to us: metadata, concepts and their parts, search, subsets, mapsets and history. The server calls these for you, pins the release in every path, and hands back the exact URL as provenance, so any answer can be checked in a browser.

Docs: Swagger UI at api-evsrest.nci.nih.gov/swagger-ui/index.html and the evsrestapi-client-SDK on GitHub.



### Slide 7: caDSR: the companion data element registry

*Time: 1:00*

The second NCI resource is caDSR, the Cancer Data Standards Registry and Repository: NCI's ISO/IEC 11179 metadata registry of Common Data Elements (CDEs), forms and models. A CDE binds a research question to its allowed answers, so data collected in different studies can be pooled.

The two complement each other. NCIt says what a thing means. A CDE says how it is collected and stored, and its parts (object class, property, each permissible value) are annotated with NCIt concepts. Example: CDE 2192199, Race Category Text.

The server has 16 caDSR tools and 11 mapping tools that join caDSR and NCIt, in the "unified" profile. Full caDSR access needs credentials, and our live caDSR testing runs against NCI's stage environment on the NIH network. So caDSR is out of scope for today's demo; the demo runs the default evs-only profile.

Precise version, if asked: most caDSR read tools work without a login, but the contexts list and CDE Match services need one, and we only run live tests against stage.

Links: caDSR II at cadsr.cancer.gov; registry listing at datacatalog.ccdi.cancer.gov/resource/caDSR.



### Slide 8: evs-cadsr-mcp at a glance

*Time: 1:00*

Architecture, left to right. Any MCP client (today VS Code with GitHub Copilot) talks MCP to the server over stdio locally, or Streamable HTTP at /mcp when hosted.

Inside the server there are three layers:

- Tools, prompts and resources: 48 tools in three families (21 EVS, 16 caDSR, 11 mapping), 11 prompts and 6 resources.
- A platform middleware chain: correlation IDs, authentication and scopes, rate limits, audit records and metrics.
- Core services: release resolution, per-call request budgets, cursors, caching, and a resilient HTTP client with retries, backoff and Retry-After support.

Facts along the bottom: it is read-only and Apache-2.0; it runs in three profiles, with evs-only (no credentials) as the default; it runs locally over stdio or hosted in FastAPI with /healthz and /metrics; and it ships a Dockerfile, an AWS CDK reference stack and a Databricks App configuration.



### Slide 9: 21 EVS tools, grouped by the job to be done

*Time: 1:00*

The 21 EVS tools are organized around jobs, not endpoints: discover releases and metadata; look up a concept by code, name or synonym; search; navigate the hierarchy; follow relationships, including a bounded multi-hop traversal; work with value sets; cross-map to other code systems; check change history; and build concept sets by rule.

Two worth calling out. evs_lookup_concept resolves a code, preferred name or synonym in one call and reports how it matched. evs_find_concepts has a small planner that picks native API routes (search, inverse roles or associations, subset members), combines them with AND or OR, and explains its plan in the answer.

There are also 5 EVS prompts, reusable workflows such as resolve_term_with_provenance and expand_cohort_terms, and 3 EVS resources for terminologies, releases and concepts.



### Slide 10: Every answer carries its receipts

*Time: 1:00*

This is what the agent actually receives: a real response from the evaluation run (evs_lookup_concept with "NSCLC", 23 Nov 2026).

The result says C2926 matched by synonym. The provenance says release 26.10d, served live, with the exact EVS URL, which you can paste into a browser. Meta carries timing and the number of upstream requests.

When something can't be answered, the error is specific and actionable. Ask for a release EVS no longer serves and you get release_not_available, the list of live releases, and a hint about what to do next.

Five principles: provenance on every answer; releases fail closed; bounded work with truncation reported; a closed set of error codes with hints; and never synthesize: absent fields stay absent, retrieved text is treated as data, and license-gated maps stay hidden without a key.



### Slide 11: Nine workflows, run against live EVS

*Time: 1:00*

We wrote nine workflows as executable test cases (docs/evs mcp use cases.md) and ran them against live EVS: 54 tool calls.

- Cohort expansion: Ewing sarcoma's 32 subtypes in one complete page, with exclusions flagged negative.
- Standard value sets: CDISC SDTM Sex has four values, and an exact search shows "F" is Female.
- Cross-terminology coding: ICD-O 8140/3 to Adenocarcinoma, and on to ICD-10-CM through Cutaneous Melanoma; MedDRA withheld without a license key.
- Grounded Q&A: NSCLC with its definition, two parents and 16 root paths.
- Release remediation: finds retired codes and the replacement for C28327, and refuses a withdrawn release.
- Drug normalization: three names, one ingredient.
- Biomarker links: EGFR L858R to the EGFR gene and 17 targeting agents.
- CTCAE: nausea grade definitions in versions 5.0 and 6.0, and no guessing for lay phrases.
- Term dictionary: a two-level lung carcinoma branch, 101 codes and 539 synonym entries from one upstream request.

52 of 54 steps pass; the two known issues are documented, and every scenario still meets its goal.



### Slide 12: Live demo in VS Code with Copilot

*Time: 6:00*

Switch to VS Code. The repo is open, the server is registered in .mcp.json (stdio, evs-only profile), and Copilot Chat is in Agent mode with the evsCadsr tools enabled.

Run the prompts in docs/presentation/demo-script.md. Core path for the 20-minute version: 1, 2, 3, 4, 6, 8. Add 5 and 7 if time allows.

While each prompt runs, narrate three things: which tool the agent picked, that the answer names the code and the release, and (once) expand a tool call to show the raw envelope with release and sourceUri.

Fallback if the network or the agent misbehaves: run the same call with scripts/call_tool.py in the terminal, or show docs/evaluation/use-case-transcript.txt.



### Slide 13: Evidence: 207 tests and 54 live calls

*Time: 1:00*

What we ran (docs/evaluation/EVALUATION.md, 23 Nov 2026, commit 3cda201):

- 207 automated tests, 0 failures, 2 skipped: unit, contract, conformance and acceptance offline (190), plus live smoke and acceptance against EVS and caDSR stage (17).
- The nine use cases: 52 of 54 live calls pass; 2 known issues documented.
- Live latency over those 54 calls: median 0.18 s, p95 0.32 s, max 0.62 s.

The chart is a deliberately honest baseline: plain keyword search over 67 test queries. Concept names, synonyms, drugs and findings score 1.0. Lay language scores 0.5, CDE-style phrasing 0.17, and definition-style phrasing 0. ICD-O codes typed as text score 0, which is why the server answers them with a property search and EVS's ICD-O mapping files instead (both pass in EVS-03).

Six findings are logged with evidence and suggested fixes. CI runs lint, offline tests on Python 3.11 and 3.12, a gitleaks secret scan and pip-audit on every push.



### Slide 14: Documentation for every audience

*Time: 0:45*

Documentation is organized by audience.

- New users: README, a five-minute QUICKSTART, and a plain-language tool guide (docs/tools/) with two examples per tool.
- Evaluators: the executable use cases, the evaluation report, and the user guide.
- Operators: deployment guide, runbook and SECURITY.md.
- Developers and coding agents: AGENTS.md, skills for adding a tool and running live tests, and the interface baseline with change control.

If time allows, switch to GitHub and click: README, QUICKSTART, docs/tools, the use cases, EVALUATION.md.



### Slide 15: Honest limits and next steps

*Time: 0:45*

Be candid. Search is keyword-only today, so definition-style and lay queries miss; the next increment is semantic and hybrid search over a release-aware NCIt index, using an embedding model NCI approves. Some concept-set combinations need SPARQL, and we report that instead of guessing. caDSR needs credentials and has been tested on stage only. Six findings are logged.

Next: fix findings F1 to F5 and freeze the interface baseline so CI blocks breaking changes; a hosted deployment with OAuth (Databricks App or AWS); and a broader evaluation with SME-validated queries and agent-level runs across several models.



### Slide 16: Thank you

*Time: 0:15*

Thank the judges. Everything is public on GitHub: the code, the QUICKSTART, the tool guide and the evaluation evidence. Invite questions. Backup slides follow: judging-criteria map, security posture, known issues, client setup, caDSR and mapping tools, and the anatomy of a tool definition.



### Slide 17: judging criteria and where to find evidence (backup)

Use if a judge asks how the submission maps to the rubric. Each row points to a file in the repository.



### Slide 18: security and deployment posture (backup)

Use for security questions. Key line: it is read-only, binds to loopback by default, and refuses to serve HTTP on any other address without JWT authentication (or the Databricks App proxy). Secrets are SecretStr settings that are never logged, cached or put in provenance URIs. Details in SECURITY.md.



### Slide 19: known issues from the evaluation (backup)

The six findings from docs/evaluation/EVALUATION.md. None stops a scenario from reaching its goal. F1 and F2 are the two known-issue steps in the use-case run.



### Slide 20: connecting a client (backup)

VS Code reads the portable .mcp.json at the repo root (top-level "mcpServers"). Claude Desktop needs absolute paths. Any client can use Streamable HTTP at http://127.0.0.1:8000/mcp; the server refuses non-loopback addresses without JWT. The default evs-only profile needs no credentials.



### Slide 21: caDSR and mapping tools (backup)

The 16 caDSR tools and 11 mapping tools in the unified profile. Key-marked tools need caDSR credentials. Mapping tools that compute verdicts or rankings label them in meta.exception, so nobody mistakes them for official NCI content.



### Slide 22: anatomy of an agent-ready tool (backup)

This is the real signature of evs_lookup_concept (src/evs_cadsr_mcp/evs/tools/evs_lookup_concept.py). Inputs are typed and validated with Pydantic (Annotated, Field, Literal), so the client gets a precise JSON schema. The docstring tells the model when to use the tool and what to use instead. The return type is the shared Envelope with provenance. The MCP layer stays thin: the logic is in evs/service.py.



## Questions to expect

**Why MCP, instead of using the EVS REST API directly?**
The REST API is excellent if you write code. MCP makes the same content usable from any AI
assistant (VS Code with Copilot, Claude, Databricks agents and others) with no custom code. The
tools are shaped around tasks rather than endpoints. `evs_lookup_concept` resolves a code, name
or synonym in one call and says how it matched. `evs_find_concepts` plans which API routes to
combine. `evs_traverse` walks the graph within limits. The server adds what an agent needs to be
trustworthy: pinned releases, provenance, request budgets and errors with hints.

**How do you stop the model from inventing codes?**
The server never makes content up. Fields the upstream didn't return stay absent, and a lookup
returns nothing rather than a near match (the "throwing up" example in the demo extras). Every code in a
tool result carries provenance: the release and the exact EVS URL. So any code the assistant
quotes can be checked, and the server's instructions tell the model to cite and never invent a
code. The model can still phrase things badly, which is why the evaluation checks the tool
results themselves, and why citations matter.

**How is this different from EVS Explore?**
EVS Explore is the official browser for people looking at one concept at a time. This server
uses the same public API, but lets an assistant chain steps (lookup, paths, relationships, maps,
history) to answer multi-step questions, and cite each step.

**Which AI models did you test with?**
The tool evaluation doesn't depend on a model: the test suite and the use-case runner call the
tools through an MCP client and check the answers directly. The demo uses GitHub Copilot in VS
Code, and QUICKSTART.md also covers Claude Code and Claude Desktop. Agent-level runs across
several models are a planned next step (slide 15).

**Plain keyword search misses lay and descriptive queries. What's the plan?**
Our baseline shows it plainly (slide 13). The next increment is semantic and hybrid search over
a release-aware NCIt index, using an embedding model NCI approves. Until then, the agent can turn
lay wording into candidate terms and check each one with exact lookup, presenting the result as a
suggestion.

**How do you keep up with monthly releases?**
A release registry reads EVS's terminology metadata. The active release is the latest monthly
one, unless the operator pins another. Every upstream call puts the release in the path
(`ncit_26.10d`), and cursors and cache keys include it. A release EVS no longer serves returns
`release_not_available`. If EVS ever answers with a different release than requested, the call
fails with `release_mismatch`.

**Is it secure? Could NCI host it?**
It is read-only and binds to 127.0.0.1 by default. It refuses to serve HTTP on any other address
without JWT authentication (issuer and audience checked, per-namespace scopes), or the Databricks
App proxy. The HTTP host enforces Host and Origin allow-lists, a 4 MiB body cap and per-client
rate limits. Audit records hash free text. Secrets are never logged, cached or put in provenance.
CI runs gitleaks and pip-audit. A Dockerfile, an AWS CDK reference stack and a Databricks App
configuration are included. See backup slide 18 and SECURITY.md.

**What about licensed content such as MedDRA?**
There is a license gate. Without `ECM_LICENSE_KEY`, MedDRA map targets are withheld in every tool
that returns maps, and a warning names them (demo extra EVS-03). With a key, it is sent only to
the gated requests and never appears in logs or provenance.

**Will this overload NCI's API?**
It is built to be a good citizen. Concurrency is bounded. It retries with backoff and jitter only
on 429 and 5xx errors, and honors Retry-After. Each tool call has a request budget, and results
are cached by content type. Batch endpoints keep request counts low: the term-dictionary scenario
fetched synonyms for 102 concepts in one request. The 54 use-case calls made 58 upstream requests
in total.

**Why isn't caDSR in the demo?**
The server includes 16 caDSR tools and 11 mapping tools, in the unified profile. Some caDSR
services (contexts and CDE Match) need credentials, and our live caDSR testing runs against NCI's
stage environment, which is only reachable on the NIH network. We kept the demo to public EVS so
anyone can reproduce it with internet access alone. caDSR was evaluated in the live acceptance
tests on stage.

**What didn't work in your evaluation?**
Two use-case steps are known issues. F1: the concept-map filter compares labels exactly, and EVS
labels these maps "ICD10CM 2017". F2: the release-impact report includes codes that were already
retired. The other findings: F3, a metadata output-validation error for concept statuses; F4, the
interface-baseline export fails on FastMCP 3.4; F5, an unwritable ICD-O cache gives the wrong
error code; and F6, an open decision for NCI. None of them stops a scenario from reaching its
goal. Each has a suggested fix (backup slide 19).

**Can clinicians use this to make decisions?**
No. The server returns terminology data as published by NCI. Relationships such as "has target"
or "has finding" are not evidence of effectiveness, eligibility or a diagnosis, and the
documentation says so in each scenario's limits.

**Why read-only?**
EVS and caDSR content has its own curation and governance. The server's job is trustworthy
retrieval, not editing.

**48 tools: isn't that too many for a model?**
Profiles control what an agent sees. The default evs-only profile, used in the demo, exposes 21
tools. Names are grouped by family, and each description says when to use the tool and what to
use instead. The server instructions and 11 prompts spell out the usual workflows.

**How long does it take to set up?**
About five minutes, following QUICKSTART.md: install uv, clone the repo, `uv sync`, then open the
folder in VS Code.



## Judging criteria and where the evidence is

The GSA hackathon page lists code quality and organization, the team's own evaluation setup and
results, agent-first tool design, innovation, mission alignment and presentation. Backup slide 17
is the short version of this table.

| Criterion | Evidence |
| --- | --- |
| Code organization | `src/evs_cadsr_mcp/` has `core/`, `evs/`, `cadsr/`, `map/` and `server/`. Each family has `client.py`, `service.py`, `models.py` and a `tools/` package with one module per tool. Logic is in services; the MCP layer stays thin. See [AGENTS.md](../../AGENTS.md) and [README.md](../../README.md). |
| Agent-first tool design | Pydantic-typed inputs with patterns, ranges and enums; descriptions that say when to use each tool and what to use instead; goal-shaped tools (`evs_lookup_concept`, `evs_find_concepts`, `evs_traverse`); server instructions and 11 prompts. See backup slide 22 and [docs/tools/](../tools/README.md). |
| Evaluation setup and results | [docs/evaluation/EVALUATION.md](../evaluation/EVALUATION.md): 207 tests (0 failures), 9 live scenarios (54 calls, 52 pass, 2 known issues), latency, retrieval baseline, 6 findings with fixes, commands to reproduce. |
| Error handling | Closed set of error codes with hints; releases fail closed; truncation and license gates reported. Demo 8. |
| Performance | Median 0.18 s, p95 0.32 s over 54 live calls; a warm cache makes no upstream calls ([benchmark](../evaluation/test-results/benchmark.md)). |
| Innovation | Provenance on every answer, release pinning, polarity-aware traversal that keeps exclusions apart, the concept-set planner with explained plans, and the license gate. |
| Mission alignment | Opens NCI's controlled vocabulary to researchers, data managers, registrars, standards teams, curators and NLP developers, through the AI tools they already use. |
| Presentation | This folder: the deck, the [demo script](demo-script.md) and these notes. |



## Fact sheet: every number in the deck and its source

Check these if anyone asks "where does that number come from?"

| Claim (slide) | Value | Source |
| --- | --- | --- |
| NCIt concepts (2) | About 178,000 (178,080) | NCI EVS wiki, [Shared Terminology Development](https://wiki.nci.nih.gov/spaces/EVS/pages/50235286/Shared+Terminology+Development) (August 2026 figures) |
| Relationships (2) | More than 400,000 | [evs.nci.nih.gov](https://evs.nci.nih.gov/) |
| Subsets (2) | More than 550, most within NCIt | [evs.nci.nih.gov](https://evs.nci.nih.gov/) |
| Monthly releases; 500+ new concepts a month (2) | | NCI EVS wiki, [EVS Resources](https://wiki.nci.nih.gov/display/EVS/EVS+Resources) and [NCI Thesaurus](https://wiki.nci.nih.gov/display/EVS/NCI+Thesaurus+(NCIt)) pages |
| License (2) | CC BY 4.0 | [NCIt terms of use](https://evs.nci.nih.gov/ftp1/NCI_Thesaurus/ThesaurusTermsofUse.htm) |
| Partners (2) | FDA, CDISC and others | NCI EVS wiki, Shared Terminology Development |
| Melanoma C3224 details (2) | 17 synonym entries from 11 sources; 4 definitions; ICD-O-3 8720/3; UMLS C0025202; roles; maps; MedDRA withheld | Live run: `use-case-results.json`, steps EVS-05.earlier-release (NCIt 26.09d), EVS-04.findings and EVS-03.melanoma-maps (26.10d) |
| NSCLC as a synonym; 2 parents; 16 paths (1, 4, 11) | C2926; parents C4878 and C65151 | Live run, steps EVS-04.lookup, EVS-04.parents and EVS-04.paths |
| Tagrisso → C170266; AZD9291 and osimertinib → C116377 (4, 11) | | Live run, EVS-06 |
| "EGFR L858R": 556 hits; #2 is "EGFR L858R Negative" (4) | C98515; C217165 | Live run, EVS-07.variant |
| "F" contains-search also returns Intersex (4) | | [docs/evs mcp use cases.md](../evs%20mcp%20use%20cases.md), EVS-02 limits |
| ICD-O codes as free text: 0 of 5 (4); recall@5 by query type (13) | | [retrieval-upstream-contains.md](../evaluation/retrieval-upstream-contains.md) |
| C28327 merged into C4029; 4 live releases (4, 11) | 2021-07-26; 26.11c, 26.10d, 26.09d, 26.08e | Live run, EVS-05.history and EVS-05.releases |
| EVS REST API on a triple store with Elasticsearch (6) | | [EVS tools page](https://evs.nci.nih.gov/tools) |
| caDSR: ISO/IEC 11179; CDE binds a question to its allowed answers; concepts mainly from NCIt (7) | | [NCI metadata services](https://www.cancer.gov/about-nci/organization/cbiit/vocabulary/metadata) |
| 48 tools (21 / 16 / 11), 11 prompts, 6 resources (8, 9) | | Repository source; [docs/tools/README.md](../tools/README.md) |
| 207 tests, 0 failures, 2 skipped; 190 offline, 17 live (13) | | [EVALUATION.md](../evaluation/EVALUATION.md), results by tier |
| 52 of 54 steps pass; 2 known issues (11, 13) | | [use-case-results.md](../evaluation/use-case-results.md) |
| Median 0.18 s, p95 0.32 s, max 0.62 s (13) | | EVALUATION.md, performance |
| 32 Ewing sarcoma subtypes; 17 agents; 101 codes and 539 synonym entries (11) | | Live run, EVS-01, EVS-07, EVS-09 |
| Six findings (13, 15, 19) | F1 to F6 | EVALUATION.md, findings |



## Wording to keep accurate

- **caDSR access.** The slide says "full caDSR access needs credentials". That is accurate: most
  caDSR read tools work without a login, but the contexts list and CDE Match services need one,
  and live testing is done only on caDSR stage. If asked, give the precise version.
- **"Real response."** Slide 10's JSON is an abridged copy of a real response from the
  evaluation run. Fields were removed for space, and none were changed.
- **Counts change monthly.** Say "as of NCIt 26.10d" if a newer release is active on the day.
  Codes and relationships are stable; counts such as 32 subtypes or 17 agents can change.
- **Tagrisso** is a synonym of the salt (Osimertinib Mesylate, C170266), not of the ingredient.
  That is NCIt's modelling, not a server quirk.
- **Melanoma and ICD-10-CM.** Melanoma (C3224) has no direct ICD-10-CM map. The ICD-10-CM codes
  sit on site-specific concepts such as Cutaneous Melanoma (C3510).
- **Not medical advice.** Returned text is upstream terminology data.
- **Dates.** The evaluation ran on the evening of 23 November 2026, US Eastern time (01:23 to
  01:30 UTC on 24 November). The deck uses 23 November.



## Glossary

| Term | Meaning |
| --- | --- |
| EVS | NCI Enterprise Vocabulary Services, which publishes NCIt and other terminologies |
| NCIt | NCI Thesaurus, NCI's reference terminology and ontology |
| NCIm | NCI Metathesaurus, which maps terms from many terminologies to shared concepts |
| Concept code | A stable NCIt identifier such as C3224. It carries no meaning in itself. |
| Preferred name, synonym | The concept's main name (term type PT) and its other names, such as SY (synonym), AB (abbreviation) and BR (brand name) |
| Role, association | Two kinds of links between concepts. A role is a defining property, such as `Disease_Has_Finding`; an association is a looser link, such as `Has_Target`. |
| Polarity | The server's label on a link: `negative` for exclusions such as `Disease_Excludes_Finding`, so they aren't treated as members |
| Subset | A published value set, such as CDISC SDTM Sex (C66731) |
| Mapset | A published mapping table from NCIt to another code system, such as `NCIt_Maps_To_ICD10CM` |
| Release | A dated NCIt version such as 26.10d (year 26, month 10, then a build letter). EVS serves monthly and weekly releases, and only the most recent few are online. |
| caDSR | The Cancer Data Standards Registry and Repository, NCI's metadata registry |
| CDE | Common Data Element: a question or variable with its allowed values |
| ISO/IEC 11179 | The international standard for metadata registries that caDSR follows |
| Permissible value | One allowed answer of a CDE, linked to a value meaning and usually an NCIt concept |
| MCP | Model Context Protocol, the open standard for connecting AI clients to tools and data |
| Tool, prompt, resource | What an MCP server offers: functions the model can call, reusable workflows, and readable context |
| stdio, Streamable HTTP | The two MCP transports this server supports: a local subprocess, or HTTP at `/mcp` |
| Envelope | The server's standard response: result, provenance, page, truncation, warnings and meta |
| Provenance | Where an answer came from: release, source URL, retrieval time, live or cache, and license status |
| Profile | Which tool families the server exposes: evs-only (default), cadsr-only or unified |



## Checklist

**The day before**

- Run the setup and the rehearsal in the [demo script](demo-script.md), sections 1 and 2.
- Read the speaker notes in Presenter View once, with a timer.
- Open the deck in PowerPoint and check that fonts render (Cambria and Calibri, both standard in
  Office).
- Decide on the 20-minute or 15-minute cut.

**On the day**

- Check the network, and that the server is running in VS Code (demo script, section 2).
- Turn on Do Not Disturb, close chat apps and set the display to mirror or extend as needed.
- Have these ready: the deck, VS Code with Copilot Chat in Agent mode, a terminal at the repo
  root, and the repository on GitHub in a browser tab.
