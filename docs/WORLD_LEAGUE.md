# Agentopia World League

## Fork It. Name Your World. Keep It Alive. Teach Us Something New.

The **Agentopia World League** turns persistent AI worlds into a community research experiment.

Every public fork can become its own city, region, language environment, occupation mix, or experimental society. Participating worlds publish a small, privacy-safe **World Beacon** that reports durable simulation progress and aggregate right-sizing research metadata.

The leaderboard is the game. The research behind it is the point.

> **What is the smallest model that can reliably perform a real task in the language and context where that task actually exists?**

## Leaderboard

The first leaderboard ranks participating forks by **committed simulation weeks completed**. Only completed, committed weeks count. An in-flight or crashed week does not.

The canonical unit remains weeks so the research stays comparable. The public display can grow with the community:

    Weeks -> Months -> Years -> Decades

Suggested display thresholds:

- fewer than 25 participating worlds: show weeks
- 25-99 worlds: add months
- 100-499 worlds: add years
- 500+ worlds: add decades

Persistence milestones:

- **Week Runner** — 1+ committed week
- **Month Builder** — 4+ committed weeks
- **Year Architect** — 52+ committed weeks
- **Decade Civilization** — 520+ committed weeks

## The Research Game

A world can compete on persistence, but it can also contribute **new work for AI to solve**.

We want contributors to add jobs, trades, professions, local workflows, business processes, public services, education, logistics, manufacturing, agriculture, healthcare, transportation, finance, arts, administrative work, and tasks we have not thought of yet.

That is how the task distribution becomes broader than one developer, one city, or one country.

Community badges include:

- **Task Pioneer** — accepted new task family
- **Trade Builder** — accepted skilled-trade or occupation pack
- **Language Pathfinder** — accepted task pack in a language not yet represented
- **Community Reviewer** — reviewed a culture/language pack from lived or fluent context
- **Persistence Builder** — crossed a world-longevity milestone

The project does **not** rank cultures, nationalities, languages, religions, or communities against one another. We rank world persistence and research contribution.

## Language First: Please Do Not Translate Yourself Into English for Us

If a task is normally performed in Spanish, Portuguese, Arabic, Korean, French, Yoruba, Hindi, Japanese, ASL gloss, a regional dialect, or another language variety, **submit the task in that language first**.

English can be added as a summary for maintainers, but English should not replace the authentic language of the work.

We want:

- the language people actually use
- the local vocabulary people actually use
- the trade terminology people actually use
- the culturally appropriate way the task is framed
- the regional context that changes how the task is performed

Use a BCP-47 language tag where possible, such as es-CO, pt-BR, en-US, or fr-CA. Do not flatten a language into one global version when regional usage matters.

A machine translation may be included for convenience, but **machine translation alone is not cultural validation**.

## Culture Comes From People, Not Guessing

Agentopia Detroit and **Kai — Transparent AI** should not invent someone else's culture.

A culture-aware Research Pack should say where its context came from:

- lived experience
- professional experience
- community review
- fluent/native language review
- published authoritative sources
- a documented combination of the above

We do **not** infer a person's culture from nationality, language, name, race, religion, location, or other identity signals.

We do **not** treat a country as one culture.

We do **not** ask Kai to manufacture stereotypes and call them local knowledge.

If a contributor does not know the context well enough to represent it, the correct action is to invite someone who does.

> **We learn from people willing to teach us, not by guessing at them.**

## Kai — Transparent AI

The World League is a public, inspectable community-learning layer for **Kai — Transparent AI**.

Community contributions can help Kai's right-sizing research evaluate:

- which task classes small local models handle well
- which languages change model performance
- which domain vocabulary increases difficulty
- when a 350M model is sufficient
- when a 1.2B model is sufficient
- when a 2.6B model is required
- when a specialist or larger model is justified
- how routing should change by task, language, and domain

The important word is **transparent**: the source task, language, contributor provenance, evaluation method, and resulting model-tier evidence can be inspected.

At this stage, World League contributions are treated as **research and evaluation inputs**. They are not silently turned into model-training or fine-tuning data. Any future training use must preserve provenance, permissions, contributor intent, and explicit consent.

The goal is for Kai to improve how it selects the right intelligence for the work **without pretending to know a culture it was never taught**.

## World Beacon

Participating forks submit one JSON beacon under research/submissions/.

The beacon reports only aggregate, non-sensitive information such as:

- world name
- public fork repository
- committed weeks completed
- coarse language/region context
- population counts
- hardware profile
- model tiers
- aggregate request counts
- aggregate success/latency data
- Research Packs in use

**Do not submit prompts, responses, credentials, private citizen histories, personal files, exact addresses, or real personal data.**

## Research Packs

Research Packs live under research/packs/.

A pack can define one or more task families. Each task should describe:

- occupation/domain
- task
- source language
- native-language task description
- optional English summary
- expected output
- evaluation method
- cultural/regional notes when relevant
- contributor provenance
- reviewer status

Specific, testable tasks create useful right-sizing evidence.

## Privacy and Research Ethics

Participation is opt-in.

Do not submit private conversations, real-person prompts or outputs, credentials, personal health/financial/account data, exact home/work addresses, copyrighted datasets you cannot redistribute, stereotypes presented as cultural truth, or discriminatory rankings of real human groups.

Culture and language metadata describe the **simulated workload context**. They are not a basis for scoring human worth or capability.

## How to Join

1. Fork Agentopia Detroit.
2. Give your world a unique name.
3. Copy research/world_profile.example.json to research/world_profile.json and edit it.
4. Run your world locally.
5. Let it reach at least one committed checkpoint.
6. Run: python scripts/export_world_beacon.py
7. Add any Research Packs you want to contribute.
8. Run: python scripts/build_leaderboard.py
9. Open a pull request back to Agentopia Detroit.

After validation and merge, your world becomes part of the public leaderboard and research dataset.

## What Success Looks Like

Today it may be Detroit and a handful of student forks.

Later it could be dozens or hundreds of independent worlds with different languages, jobs, trades, cultures, business processes, and local realities.

We should be able to watch that map of human-contributed work grow over time and see, transparently, which AI capability was actually required to perform it.
