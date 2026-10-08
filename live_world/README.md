# Agentopia Live World v0.4

Read-only graphical observer for Agentopia.

v0.4 fixes three causes of an apparently idle GUI:

1. AUTO mode follows the most recently changing generated run rather than pinning an older run.
2. Current activity is based on Agentopia's observed simulation clock and current day, not the furthest future schedule.
3. The GUI exposes engine status, simulation phase, last Agentopia file write, and live world log lines.

The launcher reuses an existing Agentopia process. If none is running it starts a smaller local-Mac visual run with 8 agents, 1 year, and 2 weeks so local Ollama can reach social/activity stages sooner.


## v0.4 animated citizen bodies

The neighborhood now renders small animated human figures instead of circles.
The visual presentation is driven only by each Agentopia profile's explicit `gender`
field (Male/Female where supplied). Unknown, non-binary, or unspecified values use
a neutral figure. The observer never infers gender from a person's name.

During the activity stage, arms and legs animate as a walking cycle. During other
stages citizens use a subtle idle animation, and the latest message sender receives
a talking animation.


## v0.7 Interiors
- Every known public building and private home has a clickable Interior View.
- Neighborhood cards open the interior directly.
- Buildings tab exposes the complete location directory, including empty homes.
- Interior occupants update from the live Agentopia snapshot every refresh.
- Recent messages are filtered to current occupants of that room.
- HQ interiors preserve TGOT red/blue and Morbeious black leader visuals.
- Speed buttons are wired to POST `/api/speed` and stay visibly selected.

### Interaction
Click any visible neighborhood building or open the **Buildings** tab to access every known home/public building. The Interior View is read-only and follows the live simulation.
