"""evs-cadsr-mcp: an MCP server over NCI EVS (NCI Thesaurus) and caDSR.

Implements the EVS, caDSR and mapping modules of ``docs/evs-cadsr-mcp-proposal.md`` on a
shared ``core`` platform.
"""

__version__ = "0.1.0"

# Interface baseline version (proposal Section 13, SOW-S16). MAJOR changes when a tool,
# argument, result field, resource, prompt, envelope or error code is removed or changes
# meaning; MINOR when something is added without affecting N-1 clients. Frozen copies live
# under spec/interface-baseline/<version>/.
INTERFACE_VERSION = "1.0"

