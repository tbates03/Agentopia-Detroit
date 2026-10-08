# Agentopia Detroit

## A Persistent AI Society Built on Agentopia

**Experimental Alpha - v1.7.4.5.1**

Agentopia Detroit is a persistent multi-agent simulation built as a fork of the original Agentopia project:

https://github.com/Neph0s/Agentopia

Detroit fork:

https://github.com/tbates03/Agentopia-Detroit

Agentopia Detroit extends the original long-horizon AI society into a persistent fictional Detroit of 2045.

## What Makes Detroit Different

Agentopia Detroit is not a chatbot demo. Citizens exist inside a persistent world and can:

- maintain long-term memories
- plan weekly goals
- meet and communicate with other citizens
- form relationships
- work and pursue careers
- earn and spend money
- participate in businesses
- attend educational activities
- experience healthcare events
- travel through a mobility network
- join factions
- participate in missions
- experience investigations and consequences
- resume across simulation checkpoints

## Major Systems

- Persistent World
- Cognitive Society
- Human Lifecycle
- Social and Relationship Systems
- ThAI Guardians
- Obsidian Network
- Mission and Justice System
- Financial System
- Career Economy
- Human Economy
- Business Economy
- Education and Skills
- Health and Healthcare
- Mobility and Time
- Digital Twin Telemetry
- Live World Observer

## Persistent Simulation

Agentopia Detroit separates the live simulation from the last committed checkpoint.

Example:

    Committed checkpoint: Week 4
    Live simulation:      Week 5 / Activity D1

The committed checkpoint is the recovery anchor. A partially completed week is not treated as durable history until it successfully completes.

## Live World Observer

The local observer normally runs at:

    http://127.0.0.1:8766

It can display simulation phase, citizens, conversations, model pools, factions, public events, economy, finance, lifecycle, healthcare, mobility, missions and other world telemetry.

## Model Architecture

Model weights are not included.

Agentopia Detroit can use OpenAI-compatible local endpoints and other backends inherited from Agentopia.

The Detroit architecture supports different model roles such as:

- social
- citizen
- strategy
- cyber
- environment / God model

Users provide and configure their own models.

## Installation

Clone:

    git clone https://github.com/tbates03/Agentopia-Detroit.git
    cd Agentopia-Detroit

Create a Python environment:

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

Create local configuration:

    cp config.example.json config.json

Do not commit config.json.

## Running Detroit

    python scripts/run_detroit_persistent.py

Local model helper scripts include:

    scripts/start_detroit_llama.sh
    scripts/stop_detroit_llama.sh
    scripts/agentopia-pool-status.sh

Review model paths, ports and hardware settings before using them.

## Private Data Is Not Included

The active development simulation is intentionally excluded.

Not included:

    data/detroit_persistent/
    logs/
    runtime/
    llm_cache/
    generations/
    backups/
    model weights
    credentials

A sanitized demo world may be provided in a later release.

## Project Status

This is experimental alpha software.

Current development areas include:

- household truth unification
- simulation performance
- context budgeting
- model routing
- repetition handling
- fail-forward recovery
- persistent-state integrity
- installation automation
- Linux portability
- hardware auto-detection

## Repository Lineage

    Neph0s/Agentopia
            |
            v
    tbates03/Agentopia-Detroit

The GitHub fork relationship is intentionally preserved.

## License and Attribution

The upstream Agentopia README states that Agentopia is released under the MIT License.

Agentopia Detroit preserves the upstream Git history and project attribution.

See NOTICE.md for additional lineage information.

## Credits

Original Agentopia:
Neph0s and Agentopia contributors

Detroit fork and project direction:
Professor Timothy E. Bates

## Why Detroit?

Detroit has repeatedly reinvented itself around transformative technology.

Agentopia Detroit explores what happens when AI agents do not simply answer a prompt, but instead have to live with what happens next.
