# Universal World Engine — Phase 1

This initial delivery establishes a world registry and guarded foreground launch for existing isolated city sandboxes. **It does not enable the Detroit AI engine for other cities**; the persistent Detroit runner and its economy, lifecycle, mobility and model integrations remain Detroit-specific.

From the repository root, after City Builder import and sandbox initialization:

```bash
python3 scripts/world_registry.py list
python3 scripts/world_registry.py validate --world chicago
python3 scripts/world_registry.py launch --world chicago --port 8777
python3 scripts/world_registry.py launch --world chicago --port 8777 --execute
```

The third command is a read-only launch plan. Only `--execute` runs the isolated City Sandbox in the foreground. Ctrl-C stops it; no existing Detroit service is signaled. Use another port for Flint.

Safety: reserved Detroit identifier, bad IDs, overlapping Detroit directories, symlink escape and observer port 8766 are rejected. Registry tests prove Chicago and Flint paths are separate.

**Remaining Phase 1 engineering:** replace the hard-coded Detroit world directory throughout persistent services by injecting world context; isolate credentials, model quotas, locks, databases, launchd service names, checkpoint recovery, and observer routing; then prove two full AI cities can run simultaneously. The current registry only manages synthetic city sandboxes.
