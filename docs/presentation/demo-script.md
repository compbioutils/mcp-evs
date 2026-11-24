# Live demo script: evs-cadsr-mcp in VS Code with GitHub Copilot

This script is for the live demo during the GSA MCP Server and SI Agent Government Hackathon
presentation (slide 12 of [the deck](evs-cadsr-mcp-hackathon-deck.pptx)). It takes **6 to 7
minutes** in a 15 to 20 minute slot. It has eight demos. Six form the core path, and two can be
added if time allows. A few extras are kept for Q&A.

Every expected value below comes from the live evaluation run on 23 November 2026 against NCIt
release **26.10d** ([docs/evaluation/](../evaluation/EVALUATION.md)). NCIt changes monthly. If a
newer monthly release is active on demo day, the **codes and relationships should still match,
but counts can drift**, for example the number of subtypes or agents. Rehearse once on the day
(section 2) and update the numbers here if they changed.



## At a glance

| # | Prompt (short form) | What it shows | Path | Time |
| --- | --- | --- | --- | --- |
| 1 | Which NCIt release are you using? | Release identity; every answer is pinned | Core | 0:30 |
| 2 | What is NSCLC, and what is it a kind of? | Synonym lookup, definition, parents, provenance (EVS-04) | Core | 1:15 |
| 3 | Are Tagrisso, AZD9291 and osimertinib the same drug? | Brand, code and generic names; salt and ingredient (EVS-06) | Core | 1:00 |
| 4 | List all subtypes of Ewing sarcoma; keep exclusions apart | Complete descendants; exclusions flagged negative (EVS-01) | Core | 1:15 |
| 5 | CDISC SDTM values for Sex; is "F" valid? | Value set members; exact, filtered search (EVS-02) | Optional | 0:45 |
| 6 | Which agents target EGFR L858R? | Search trap avoided; reverse association with a plan (EVS-07) | Core | 1:00 |
| 7 | Which of these codes are retired? | Batch status, missing codes, history (EVS-05) | Optional | 1:00 |
| 8 | Show C3224 as of release 25.01d | Fails closed with a hint (error handling) | Core | 0:45 |

For a 15-minute slot, run 1, 2, 3, 4 and 8 (about 4.5 minutes).



## 1. Setup (the day before)

You need the repo, Python 3.11+, [uv](https://docs.astral.sh/uv/), VS Code with GitHub Copilot,
and internet access to `api-evsrest.nci.nih.gov`. The EVS API is public, so no VPN or
credentials are needed for this demo.

1. **Install from the lock file** (repo root):

   ```bash
   uv sync --frozen --extra dev
   ```

2. **Use the evs-only profile.** Your `.env` already sets `ECM_PROFILE=evs-only`. That gives
   the agent 21 EVS tools and no caDSR tools, so it has fewer tools to choose between and needs
   no credentials. Make sure `ECM_RELEASE_PIN` is not set, so the server uses the latest monthly
   release.

3. **Check the server without an AI client:**

   ```bash
   uv run --no-sync python scripts/check_server.py                 # exit 0 = server works
   uv run --no-sync python scripts/call_tool.py --mode live evs_list_releases
   ```

4. **Rehearse the scenarios against today's release.** Write the results to a scratch folder,
   so the submitted evidence in `docs/evaluation/` isn't overwritten:

   ```bash
   uv run --no-sync python scripts/run_use_cases.py --out "$TMPDIR/uc-rehearsal"
   ```

   It takes about 15 seconds. If the active release is no longer 26.10d, compare counts with the
   expected values below.

5. **Connect VS Code.** Open the repo folder and trust the workspace. VS Code's Copilot reads the
   portable `.mcp.json` at the repo root (top-level `mcpServers`), which starts the server over
   stdio with `uv run --no-sync evs-cadsr-mcp serve --transport stdio`. Then:
   - Open Copilot Chat and switch the mode to **Agent**. MCP tools are available only in Agent mode.
   - Open the tools picker in the chat box. Confirm that **evsCadsr** is listed with 21 tools.
   - **Turn off tools you won't use**, especially web search or fetch tools and other MCP servers,
     so the agent answers from EVS and not from the web.
   - Run one throwaway prompt. When VS Code asks to approve the tool call, pick an option that
     allows it for the session or workspace, so approvals don't interrupt the demo. If you want to
     show human-in-the-loop approval, leave it on for demo 1 only.

6. **Pick the model you rehearsed with** in Copilot's model picker, and keep it for the demo.
   Tool selection varies a little between models.

7. **Prepare the screen.** Zoom VS Code so the chat is readable from the back of the room
   (Cmd and = on macOS), close the sidebars you don't need, and keep these ready in other tabs:
   - a terminal at the repo root, for the scripted fallbacks in section 5;
   - [docs/evaluation/use-case-results.md](../evaluation/use-case-results.md) on GitHub, in case
     the network fails;
   - optionally, a screen recording of a clean run.
   
   

## 2. Pre-flight (5 minutes before you present)

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://api-evsrest.nci.nih.gov/api/v1/metadata/terminologies   # expect 200
uv run --no-sync evs-cadsr-mcp releases                                                              # note "active"
```

In VS Code, run **MCP: List Servers** from the Command Palette and check that `evsCadsr` is
running. Restart it if needed. Then open a **new chat** in Agent mode.

One chat can carry the whole demo. If replies slow down as the conversation grows, start a new
chat. The server keeps no state between calls.



## 3. The demos

Each demo lists the prompt to paste, the tools the agent should call, what you should see, what
to say, and what to do if it goes sideways. Agents word things differently each run, so check
the **codes**, not the exact wording.



### Demo 1: Which release? (warm-up, 0:30)

```text
Use the evsCadsr tools. Which NCIt release are you using, and which releases could I pin to?
```

- **Tools:** `evs_list_releases`.
- **Expect:** active release **26.10d** (monthly, 2026-10-26). Live releases: 26.11c (weekly,
  2026-11-16), 26.10d, 26.09d and 26.08e.
- **Say:** "Every answer from here on is pinned to this release, and the server will refuse to
  mix releases."
- **Fallback:** `uv run --no-sync python scripts/call_tool.py --mode live evs_list_releases`



### Demo 2: Grounded Q&A (EVS-04, 1:15)

```text
What is NSCLC in the NCI Thesaurus? Give the code, the preferred name, the NCI definition, and what it is a kind of. Cite the release.
```

- **Tools:** `evs_lookup_concept` (`identifier: "NSCLC"`), then `evs_get_concept` with
  definitions, then `evs_get_hierarchy_neighbors` (parents) or `evs_get_paths`.
- **Expect:**
  - **C2926, "Lung Non-Small Cell Carcinoma"**, matched by **synonym**. "NSCLC" is an NCI
    abbreviation (term type AB) of the preferred name.
  - NCI definition beginning "A group of at least three distinct histological types of lung
    cancer, including non-small cell squamous cell carcinoma, adenocarcinoma, and large cell
    carcinoma..."
  - Parents **C4878 Lung Carcinoma** and **C65151 Non-Small Cell Carcinoma**. If the agent
    calls `evs_get_paths`, there are **16 paths** to the root.
  - Release **26.10d**.
- **Show (once):** expand the `evs_lookup_concept` tool call in the chat to show the raw
  envelope: `matchKind: "synonym"`, `provenance.release: "26.10d"`, `servedBy: "live"` and the
  `sourceUri`. Paste the `sourceUri` into a browser to show EVS's own JSON for the same query.
- **Say:** "The preferred name isn't what most people type. The server matched the synonym, says
  so, and gives the exact EVS URL behind the answer."
- **Fallback:**

  ```bash
  uv run --no-sync python scripts/call_tool.py --mode live evs_lookup_concept identifier=NSCLC
  uv run --no-sync python scripts/call_tool.py --mode live evs_get_hierarchy_neighbors direction=parents code=C2926
  ```



### Demo 3: Drug normalization (EVS-06, 1:00)

```text
Are Tagrisso, AZD9291 and osimertinib the same drug? Resolve each name to NCIt and explain how the concepts are related.
```

- **Tools:** `evs_lookup_concept` three times, then `evs_get_relationships` on C170266
  (associations). The agent may also call `evs_get_concept` for the FDA UNII or `evs_get_paths`.
- **Expect:**
  - **Tagrisso → C170266 Osimertinib Mesylate** (the salt). Tagrisso is a brand-name synonym
    (term type BR).
  - **AZD9291 → C116377 Osimertinib** (synonym) and **osimertinib → C116377** (preferred name).
  - Link: **C170266 `Has_Free_Acid_Or_Base_Form` → C116377**.
  - If asked: FDA UNII **3C06JJ0Z2O** on C116377; class **C2167 Epidermal Growth Factor
    Receptor Tyrosine Kinase Inhibitor**.
- **Say:** "Three names land on two concepts: the brand on the salt, the code name and generic on
  the ingredient. The server reports the published link. Rolling up to the ingredient is the
  abstractor's decision."
- **Fallback:**

  ```bash
  uv run --no-sync python scripts/call_tool.py --mode live evs_lookup_concept identifier=Tagrisso
  uv run --no-sync python scripts/call_tool.py --mode live evs_get_relationships code=C170266 kinds=associations names=Has_Free_Acid_Or_Base_Form
  ```



### Demo 4: Cohort expansion with exclusions (EVS-01, 1:15)

```text
I'm building a research cohort for Ewing sarcoma. List every subtype in NCIt, and list any exclusion relationships separately so I don't mix them into the cohort.
```

- **Tools:** `evs_lookup_concept`, then `evs_get_descendants` on C4817, then
  `evs_get_relationships` (roles). Some models use `evs_traverse` instead, which is also correct.
- **Expect:**
  - **C4817 Ewing Sarcoma.** The exact lookup also matches C103038, a CTEP subset concept, by
    synonym. The agent should choose C4817; if it doesn't, say "use the disease concept, C4817."
  - **32 descendants in one complete page** (no `nextCursor`), for example C4835 Bone Ewing
    Sarcoma, C7135 Extraskeletal Ewing Sarcoma and C189002 Childhood Ewing Sarcoma.
  - Exclusions with **`polarity: "negative"`**, for example `Disease_Excludes_Finding` →
    C36122 Benign Cellular Infiltrate, `Disease_Excludes_Cytogenetic_Abnormality` → C165668 CIC
    Gene Rearrangement, and `Disease_Excludes_Molecular_Abnormality` → C178457 EWSR1-NFATC2
    Fusion Protein Expression.
- **Say:** "All 32 subtypes, and the server says the list is complete. Exclusions are marked
  negative so they can't slip into the cohort. Whether to include childhood or recurrent
  subtypes is the analyst's call."
- **Optional, to show MCP prompts:** type `/` in the chat and pick the server's
  `expand_cohort_terms` prompt (VS Code lists MCP prompts as slash commands, named like
  `mcp.evsCadsr.expand_cohort_terms`), with code `C4817`.
- **Fallback:**

  ```bash
  uv run --no-sync python scripts/call_tool.py --mode live evs_get_descendants code=C4817 limit=500
  uv run --no-sync python scripts/call_tool.py --mode live evs_get_relationships code=C4817 kinds=roles
  ```



### Demo 5: CDISC value set (EVS-02, optional, 0:45)

```text
What are the CDISC SDTM values for Sex (codelist C66731)? Is "F" a valid CDISC submission value, and which concept does it mean?
```

- **Tools:** `evs_get_subset_members` (C66731), then `evs_search_concepts` with `term: "F"`,
  `type: "match"`, `subset: "C66731"` and `synonymSource: "CDISC"`.
- **Expect:** **C16576 Female, C45908 Intersex, C20197 Male, C17998 Unknown.** The exact,
  filtered search for "F" returns **only C16576 Female**.
- **Say:** "A contains-search for 'F' would also return Intersex, because its CDISC synonym
  contains the letter. Exact matching inside the codelist gives one answer."
- **Fallback:**

  ```bash
  uv run --no-sync python scripts/call_tool.py --mode live evs_get_subset_members code=C66731
  uv run --no-sync python scripts/call_tool.py --mode live evs_search_concepts term=F type=match subset=C66731 synonymSource=CDISC
  ```



### Demo 6: Biomarker to targeting agents (EVS-07, 1:00)

```text
Which agents in NCIt target the EGFR L858R mutation? Show the variant's NCIt code first.
```

- **Tools:** `evs_search_concepts` ("EGFR L858R"), then `evs_find_concepts` with
  `{"kind": "association", "name": "Has_Target", "targetCode": "C98515"}`.
- **Expect:**
  - The search reports **556 hits**. The first is **C98515 "EGFR NP_005219.2:p.L858R"**. The
    second is **C217165 "EGFR L858R Negative"**, which means the opposite. The agent should pick
    C98515.
  - **17 agents**, complete on one page, including **C116377 Osimertinib**, **C148147
    Lazertinib**, C132023 Olafertinib, C170266 Osimertinib Mesylate and C209347 Andamertinib.
  - `result.plan` shows one `inverseAssociations` route with `complete: true`.
- **Say:** "The second search hit means the opposite of what we asked for. The agent checked,
  picked the variant, and the server's planner explains how it found the 17 agents. These are
  terminology relationships, not treatment recommendations."
- **Fallback:**

  ```bash
  uv run --no-sync python scripts/call_tool.py --mode live evs_search_concepts term="EGFR L858R" limit=5
  uv run --no-sync python scripts/call_tool.py --mode live evs_find_concepts '{"criteria": [{"kind": "association", "name": "Has_Target", "targetCode": "C98515"}], "limit": 100}'
  ```



### Demo 7: Release remediation (EVS-05, optional, 1:00)

```text
Check these NCIt codes against the current release: C3224, C2926, C28327, C7681, C9324, C99999999. Which are active, which are retired, which don't exist, and what replaced the retired ones?
```

- **Tools:** `evs_get_concepts` (one batch call), then `evs_get_concept_history` for the retired
  codes.
- **Expect:**
  - Active: **C3224 Melanoma**, **C2926 Lung Non-Small Cell Carcinoma**.
  - Retired (`Retired_Concept`): **C28327 Endocervical Carcinoma**, **C7681 Carcinoma In Situ
    in a Polyp**, **C9324 Adrenal Gland Carcinoma**.
  - Missing: **C99999999** (listed in `result.missing`, not guessed).
  - History: **C28327 was merged into C4029 Cervical Adenocarcinoma on 2021-07-26.** The
    evaluation checked history for C28327 only, so read the replacements for C7681 and C9324
    from the tool output.
- **Say:** "One batch call sorts active, retired and unknown codes, and history gives the
  replacement. A retired code with no replacement goes to a curator."
- **Fallback:**

  ```bash
  uv run --no-sync python scripts/call_tool.py --mode live evs_get_concepts '{"codes": ["C3224", "C2926", "C28327", "C7681", "C9324", "C99999999"], "include": ["minimal"]}'
  uv run --no-sync python scripts/call_tool.py --mode live evs_get_concept_history code=C28327
  ```



### Demo 8: Fail closed (error handling, 0:45)

```text
Show me NCIt concept C3224 exactly as it was in release 25.01d.
```

- **Tools:** `evs_get_concept` with `release: "25.01d"`.
- **Expect:** error **`release_not_available`**, with `details.live` listing 26.10d, 26.09d,
  26.11c and 26.08e, and the hint "Pass one of details.live as `release`, or omit `release` for
  the active release." The agent should explain this and offer the oldest live release (26.08e).
  It must **not** quietly answer from today's data.
- **Say:** "That's graceful error handling: a specific code, the valid choices and a hint. No
  silent fallback to current content, because a wrong release is worse than no answer."
- **Fallback:** `uv run --no-sync python scripts/call_tool.py --mode live evs_get_concept code=C3224 release=25.01d`
  (exits with status 1 and prints the error envelope).



### Extras for Q&A

These came up in the evaluation and make good answers to "can it do X?"

- **ICD-O to NCIt, and cross-maps (EVS-03):**
  "A registry record has ICD-O-3 code 8140/3. What's the NCIt concept? Then show what Melanoma
  (C3224) maps to in other code systems."
  `evs_find_concepts` with the `ICD-O-3_Code` property gives **C2852 Adenocarcinoma** (plan:
  one search route, complete). `evs_get_concept_maps` on C3224 gives ICD-O-3 **8720/3**
  "Malignant melanoma, NOS" and GDC "Melanoma, NOS". MedDRA is **withheld with a warning**,
  because no license key is configured (the license gate).
- **CTCAE grades (EVS-08):** "What are the CTCAE v5.0 grade definitions for nausea?"
  Terminology `ctcae5`, release `5.0`: **C146764 Nausea**, with grade children C57213, C57336
  and C57467. The grade 3 definition is "Inadequate oral caloric or fluid intake; tube feeding,
  TPN, or hospitalization indicated." Follow up with "Is 'throwing up' an NCIt term?" The exact
  lookup returns nothing rather than a near match. The agent may then search and suggest
  Vomiting (C3442), and should present it as a suggestion.
- **Term dictionary (EVS-09):** "Build a term list for Lung Carcinoma (C4878), two levels deep,
  with synonyms." The result is **101 descendant codes** plus the root, with **539 synonym
  entries** from one batch request. The output is long, so point at the counts rather than
  reading it out.
- **MCP resources:** in the chat, **Add Context**, then **MCP Resources**, then attach
  `evs://ncit/releases`, if your VS Code version lists resources.



## 4. If something goes wrong

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| `evsCadsr` doesn't appear in the tools picker | Workspace not trusted, or VS Code can't find `uv` | Trust the workspace. Run **MCP: List Servers**, start `evsCadsr` and open its output. If `uv` isn't found, change `command` in `.mcp.json` to the absolute path of `.venv/bin/evs-cadsr-mcp`, with `args` `["serve", "--transport", "stdio"]`. |
| The agent answers from memory without calling tools | Ask mode, or no hint to use the tools | Check that the mode is **Agent**. Add "Use the evsCadsr tools and cite the release," or reference a tool directly, for example `#evs_lookup_concept`. |
| The agent uses web search instead | Other tools enabled | Turn off web and fetch tools and other servers in the tools picker. |
| `release_not_available` on ordinary prompts | `ECM_RELEASE_PIN` set to an old release | Remove it from `.env` and restart the server. |
| Slow replies or timeouts | EVS upstream or network | Retry once. Then switch to the scripted fallback (section 5), or show [use-case-results.md](../evaluation/use-case-results.md). |
| Counts differ from this script | A new NCIt monthly release | Codes should still match. Say "NCIt changes monthly; the codes are stable." |
| Approval prompts interrupt the flow | Per-call approval | Choose an allow option for the session or workspace. |



## 5. Scripted fallback (no LLM)

If the agent misbehaves or the network is unreliable, run the same calls directly. This is also
a good way to show judges the raw envelopes. Run from the repo root. Single quotes keep zsh from
expanding the JSON.

```bash
T="uv run --no-sync python scripts/call_tool.py --mode live"
$T evs_list_releases
$T evs_lookup_concept identifier=NSCLC
$T evs_get_hierarchy_neighbors direction=parents code=C2926
$T evs_lookup_concept identifier=Tagrisso
$T evs_get_relationships code=C170266 kinds=associations names=Has_Free_Acid_Or_Base_Form
$T evs_get_descendants code=C4817 limit=500
$T evs_get_relationships code=C4817 kinds=roles
$T evs_get_subset_members code=C66731
$T evs_search_concepts term=F type=match subset=C66731 synonymSource=CDISC
$T evs_search_concepts term="EGFR L858R" limit=5
$T evs_find_concepts '{"criteria": [{"kind": "association", "name": "Has_Target", "targetCode": "C98515"}], "limit": 100}'
$T evs_get_concepts '{"codes": ["C3224", "C2926", "C28327", "C7681", "C9324", "C99999999"], "include": ["minimal"]}'
$T evs_get_concept_history code=C28327
$T evs_get_concept code=C3224 release=25.01d
```

`--mode live` runs the server in-process against live EVS. If the HTTP server is already running
(`uv run --no-sync evs-cadsr-mcp serve --transport http --port 8000`), use
`--mode http --url http://127.0.0.1:8000/mcp` instead.

To replay all nine scenarios in about 15 seconds:
`uv run --no-sync python scripts/run_use_cases.py --out "$TMPDIR/uc-rehearsal"`.



## 6. After the demo

Point the judges to:

- [QUICKSTART.md](../../QUICKSTART.md) to reproduce the setup in about five minutes;
- [docs/evs mcp use cases.md](../evs%20mcp%20use%20cases.md), the nine scenarios this demo
  draws from;
- [docs/evaluation/EVALUATION.md](../evaluation/EVALUATION.md), with every result, finding and
  the commands to reproduce them.



## Copy-paste prompt list

```text
Use the evsCadsr tools. Which NCIt release are you using, and which releases could I pin to?

What is NSCLC in the NCI Thesaurus? Give the code, the preferred name, the NCI definition, and what it is a kind of. Cite the release.

Are Tagrisso, AZD9291 and osimertinib the same drug? Resolve each name to NCIt and explain how the concepts are related.

I'm building a research cohort for Ewing sarcoma. List every subtype in NCIt, and list any exclusion relationships separately so I don't mix them into the cohort.

What are the CDISC SDTM values for Sex (codelist C66731)? Is "F" a valid CDISC submission value, and which concept does it mean?

Which agents in NCIt target the EGFR L858R mutation? Show the variant's NCIt code first.

Check these NCIt codes against the current release: C3224, C2926, C28327, C7681, C9324, C99999999. Which are active, which are retired, which don't exist, and what replaced the retired ones?

Show me NCIt concept C3224 exactly as it was in release 25.01d.
```
