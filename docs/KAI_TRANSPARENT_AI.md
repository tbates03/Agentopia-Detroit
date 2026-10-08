# Kai — Transparent AI Community Learning

## Why This Is Transparent

Kai is intended to learn about the **work people actually do** without pretending that one developer can accurately invent every language, culture, profession, or local business process.

Agentopia World League gives that idea a public research mechanism.

A contributor can say:

- this is my language
- this is how this task is actually described
- this is the terminology used in my trade or profession
- this is the regional context that matters
- this is how success should be evaluated

Then the project can test different right-sized models against that contribution and publish aggregate results.

The chain is inspectable:

    Contributor
        |
        v
    Native-language task + provenance
        |
        v
    Research Pack
        |
        v
    Right-sizing evaluation
        |
        +--> 350M sufficient?
        +--> 1.2B sufficient?
        +--> 2.6B sufficient?
        +--> specialist/larger model required?
        |
        v
    Aggregated research evidence
        |
        v
    Kai routing / architecture research

## We Do Not Guess at Culture

Kai should not infer cultural truth from someone's name, nationality, race, religion, location, or language.

Culture-aware knowledge should come from people and sources that can explain where it came from.

That provenance can include lived experience, professional experience, fluent/native-language review, community review, and authoritative sources.

The project explicitly welcomes disagreement inside countries and languages. A country is not one culture, and a language is not one uniform vocabulary.

## Native Language Is the Primary Artifact

Contributors are asked to submit the task in the language in which the work is actually performed.

An English summary is useful for maintainers, but it is secondary.

This lets the research observe something important: model size and routing requirements may change when the same type of work is expressed in a different language, dialect, professional vocabulary, or local context.

## Research Before Training

World League data is first treated as research/evaluation data.

A Research Pack has separate consent fields for public research/evaluation and future training/fine-tuning.

Training consent is not implied by submitting a benchmark.

This separation is deliberate. A transparent system should make it clear what a contribution is being used for.

## What Kai Can Learn From This

The system can build evidence about:

- task complexity
- language
- domain terminology
- occupation/trade
- regional workflow differences
- model-tier success
- latency
- escalation rate
- reliability under persistence
- hardware cost

The purpose is not to create a universal cultural score.

The purpose is to improve **task routing** so Kai can use the smallest sufficient model while respecting the context in which the task exists.

## Community Principle

> **Do not make people translate themselves into our assumptions. Let them teach the system how the work is actually done.**

That is the community-learning principle behind Kai and the Agentopia World League.
