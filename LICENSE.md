# SKI Framework — Licensing Summary

The SKI Framework uses a **dual license** so that the right tool is
licensed under the right instrument:

| Part of the repo | License | File |
|---|---|---|
| Specification documents (`docs/`, framework PDF, diagrams) | Creative Commons Attribution 4.0 International (CC BY 4.0) | [LICENSE-docs.md](./LICENSE-docs.md) |
| Software (Python, Dockerfiles, shell, SQL, YAML, the conformance suite) | Apache License 2.0 | [LICENSE](./LICENSE) |
| Knowledge Graph libraries (energy, finance, manufacturing, defense) | Proprietary — available via [KpiFinity](https://kpifinity.com) | not in this repository |

We split the license because Creative Commons themselves
[explicitly recommend against](https://creativecommons.org/faq/#can-i-apply-a-creative-commons-license-to-software)
using CC licenses for software. CC licenses don't address patent grants
or the source/object code distinction, both of which matter for adopters
in regulated industries. Apache 2.0 includes an explicit patent grant
and is the de facto choice for open-core infrastructure software.

For the legal text, see [`LICENSE`](./LICENSE) and
[`LICENSE-docs.md`](./LICENSE-docs.md). Attribution requirements are
listed in [`NOTICE`](./NOTICE).
