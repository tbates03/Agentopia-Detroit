# World Beacon Submissions

One JSON file per participating public world.

Generate yours with:

    python scripts/export_world_beacon.py

The file should contain aggregate metadata only.

Never submit prompts, model responses, private citizen histories, credentials, exact addresses, or other personal/private data.

After adding or updating a beacon, regenerate the leaderboard:

    python scripts/build_leaderboard.py
