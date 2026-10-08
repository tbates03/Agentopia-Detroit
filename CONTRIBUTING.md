# Contributing to Agentopia Detroit

Agentopia Detroit is an experimental fork of Neph0s/Agentopia.

Contributors should:

1. preserve upstream attribution
2. never commit credentials or private simulation state
3. protect persistent-world compatibility
4. avoid destructive checkpoint changes
5. document changes to simulation semantics
6. compile and test source before submitting changes

Basic validation:

    python3 -m compileall -q src scripts

Persistent-world changes should consider:

- committed checkpoints
- partially completed weeks
- cleanup and replay behavior
- append-only JSONL data
- backward compatibility
- crash recovery
- state integrity

Pull requests should describe what changed, why it changed, affected subsystems and how the change was tested.


## World League Research Contributions

Agentopia Detroit welcomes public World Beacon and Research Pack contributions.

### Fork / World submissions

A participating world should:

1. have a public fork/repository
2. use a unique world_id and world_name
3. report **committed checkpoint progress**, not an in-flight week
4. export only aggregate, privacy-safe telemetry
5. regenerate LEADERBOARD.md before opening a pull request

Generate a beacon with:

    python scripts/export_world_beacon.py
    python scripts/build_leaderboard.py

### Language-first contributions

**Submit tasks in the language in which the work is actually performed.**

Do not rewrite a Colombian Spanish workflow into English just to make it easier for the repository maintainers. Do not flatten Brazilian Portuguese, Canadian French, regional Arabic, or another language variety into a generic version if the regional language changes the task.

An English summary may be added, but it is secondary.

### Cultural provenance

Do not guess at someone else's culture.

For culturally or regionally specific tasks, explain how the context was validated. Accepted provenance includes lived experience, professional experience, fluent/native-language review, community review, and authoritative sources.

Do not infer cultural truth from a contributor's name, nationality, race, religion, location, or language.

### Research vs. training consent

Research Packs explicitly separate:

- public research/evaluation consent
- future model training/fine-tuning consent

Training consent is optional. Submitting a benchmark does not silently grant training permission.

See docs/WORLD_LEAGUE.md and docs/TAI_TRANSPARENT_AI.md.
