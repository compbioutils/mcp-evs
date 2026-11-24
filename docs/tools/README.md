# Tool guide

This guide explains every tool the `evs-cadsr-mcp` server offers, in plain language, with two
simple examples for each one.

You normally don't call these tools yourself. You ask an AI assistant a question, such as
*"What is NCIt code C3224?"*, and the assistant chooses a tool and fills in the inputs. The
examples show those inputs, so you can see what each tool needs and try it directly if you want.

## The three tool families

| Family | What it covers | Guide |
|---|---|---|
| `evs_*` (21 tools) | The **NCI Thesaurus (NCIt)**: medical concepts, their names, codes, hierarchy, relationships and value sets. Served by NCI EVS. | [EVS tools](evs-tools.md) |
| `cadsr_*` (16 tools) | **caDSR Common Data Elements (CDEs)**: standard data fields used on forms and in data models, with their allowed values. | [caDSR tools](cadsr-tools.md) |
| `map_*` (11 tools) | **Connecting the two**: which concepts a CDE uses, which CDEs use a concept, and how a data model lines up with both. | [Mapping tools](map-tools.md) |

## Which tools are available?

The server runs in one of three **profiles**. The profile decides which families appear.

| Profile | Families shown | How to start it |
|---|---|---|
| `evs-only` (default) | `evs_*` | `evs-cadsr-mcp serve --transport http` |
| `cadsr-only` | `cadsr_*` | `evs-cadsr-mcp serve --transport http --profile cadsr-only` |
| `unified` | all three | `evs-cadsr-mcp serve --transport http --profile unified` |

A few caDSR tools also need a caDSR login (`ECM_CADSR_USERNAME` and `ECM_CADSR_PASSWORD`). Without one they reply
with `capability_unavailable` and say what is missing. Those tools are marked 🔑 in the guides.

## Inputs that many tools share

| Input | What it means | Default |
|---|---|---|
| `release` | Which monthly NCIt release to use, such as `"26.09d"`. Use it when you need answers that stay the same over time. | The server's current release |
| `terminology` | Which EVS terminology to read. | `"ncit"` |
| `limit` and `cursor` | Results arrive one page at a time. `limit` sets the page size. To get the next page, pass the `nextCursor` value from the previous answer as `cursor`. | Varies by tool |

EVS keeps only the last few releases online. Ask for an older one and you get
`release_not_available`; use [`evs_list_releases`](evs-tools.md#evs_list_releases) to see
which are available.

## What an answer looks like

Every tool returns the same wrapper:

| Part | What it tells you |
|---|---|
| `result` | The answer itself. |
| `provenance` | Where the answer came from: the source, the NCIt release, the exact upstream web address and when it was retrieved. **Cite this.** |
| `page` | Paging details, including `nextCursor` when there is more. |
| `truncation` | Present when the tool stopped early because it reached a limit. `bound` names the limit. |
| `warnings` | Anything you should know about the answer. |
| `meta` | Request details. `meta.exception` is set when **this server**, not NCI, computed a verdict or ranking. Treat those as suggestions. |

## When something goes wrong

Errors use a short, fixed list of codes:

| Code | Meaning | What to do |
|---|---|---|
| `not_found` | The code or ID doesn't exist. | Check the spelling, or search instead. |
| `invalid_request` | An input is wrong or missing. | Read the message; it names the problem. |
| `release_not_available` | That NCIt release is no longer online. | Omit `release`, or pick one from `evs_list_releases`. |
| `release_mismatch` | EVS answered with a different release than requested. | Retry later; the server refuses to mix releases. |
| `capability_unavailable` | The server or upstream can't do this, often because a login isn't configured. | Read the message; it says what is missing. |
| `license_required` | The content needs a license key. | Ask the operator to configure `ECM_LICENSE_KEY`. |
| `cursor_expired` | The page cursor is for a different release or item. | Start the search again without `cursor`. |
| `bound_exceeded`, `rate_limited`, `upstream_unavailable`, `timeout` | Too much work, too many calls, or the upstream service is unavailable. | Narrow the request or try again later. |

## Known issues (checked 19 November 2026)

These were found by running the documented examples against live EVS (NCIt 26.10d):

- [`evs_get_terminology_metadata`](evs-tools.md#evs_get_terminology_metadata) fails when
  `kinds` includes `conceptStatuses`. Other kinds work.

caDSR and mapping examples were checked against the test fixtures, not production caDSR. The
exception is [`map_map_icdo_to_ncit`](map-tools.md#map_map_icdo_to_ncit), which uses only EVS
and was also checked live.

## Related documents

- [User and developer guide](../user-guide.md): connecting, release pinning and example prompts.
- [Deployment guide](../deployment.md): running the server remotely.
