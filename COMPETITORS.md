# KAAT positioning and implementation choices

KAAT is a floating, Hinglish-first desktop companion, with video cleanup as its first supported workflow. It combines existing speech recognition, reversible editing decisions, persistent approved preferences and MCP tools. It does not claim those individual capabilities are novel.

The implementation keeps the existing Python/Tkinter/FFmpeg architecture. Importing another complete editor would add a second interface, overlapping pipelines and substantial model/runtime dependencies. Standard-library transcript similarity and FFmpeg analysis cover this MVP; Gnani Prisma is the primary speech recognizer.

The current evidence for the seven requested open-source repositories, including architecture, dependencies, licenses, exact reviewed commits and concrete reuse decisions, is in [docs/REUSE.md](docs/REUSE.md). Runtime attribution is in [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md).

Public product marketing, a public connector repository and publicly licensed editor source are different things. No proprietary competitor code or noncommercial-licensed editor code was copied into KAAT. Planned integrations are not described as completed functionality. See [docs/VALIDATION.md](docs/VALIDATION.md) for implemented/tested boundaries.
