# Agentopia Detroit launchd recovery

Agentopia Detroit uses the per-user macOS LaunchAgent label:

`com.agentopia.detroit.persistent`

A successful RC2 live migration proved that the simulation can run through the
guarded direct-service fallback, but the first live RC2 deployment also exposed
a stale/broken launchd registration:

- `Bootstrap failed: 5: Input/output error`
- service label absent from the user's GUI domain

The repair tooling regenerates the LaunchAgent rather than trying to preserve a
possibly malformed or stale plist.

## Repair

From the public checkout:

```bash
./REPAIR-AGENTOPIA-DETROIT-LAUNCHD.command
```

The repair:

1. locates the live world (default `$HOME/AI/Agentopia`)
2. backs up the existing plist under the live backup directory
3. generates a fresh plist using Python's `plistlib`
4. points launchd to the live `start_detroit_persistent_service.sh`
5. sets the live working directory and `AGENTOPIA_HOME`
6. writes stdout/stderr to the live logs directory
7. validates the plist with `plutil -lint`
8. normalizes permissions to 0644
9. removes stale launchd registrations
10. bootstraps the service into `gui/<uid>`
11. kickstarts it
12. proves the service exists with `launchctl print`
13. waits for the observer and Detroit engine to become healthy

Success means the persistent world is being supervised by launchd again.

## Controlled persistence verification

After the repair succeeds, first verify a service recycle—not a full machine
reboot:

```bash
launchctl kickstart -k "gui/$(id -u)/com.agentopia.detroit.persistent"
```

Then verify:

```bash
launchctl print "gui/$(id -u)/com.agentopia.detroit.persistent"
curl -fsS http://127.0.0.1:8766/api/health
pgrep -af run_detroit_persistent.py
```

A full Mac reboot should only be used after the controlled launchd recycle
passes. The world checkpoint remains the persistence authority; launchd is only
the process supervisor.
