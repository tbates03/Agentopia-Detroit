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
