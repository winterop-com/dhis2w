# Example Implementation Guide projects

Nine complete `d2w fhir init` project trees, one per feature story, all built
against the seeded local DHIS2 instance (`make dhis2-run`, DHIS2 2.43.1). Where
[`../cli/`](../cli/) shows one command apiece and [`../client/`](../client/README.md)
shows one library call apiece, these show the whole thing: a project you can read
top to bottom, regenerate, and compile.

Every tree here is browsable on GitHub as it stands. What is committed is the
**input** - `fhir.toml`, the SUSHI skeleton, the Makefile, the Dockerfile - and
nothing that `d2w fhir generate` or SUSHI writes.

| Guide | The story | Selection |
| --- | --- | --- |
| [`aggregate-minimal`](aggregate-minimal/) | The smallest complete guide: the forms, one district, no category axes | EPI Stock, Supervision visit, ANC follow-up; Kambia |
| [`aggregate-disaggregated`](aggregate-disaggregated/) | The same selection with every category axis published - the category pairs and their ConceptMaps | EPI Stock, Supervision visit, ANC follow-up; Kambia |
| [`event-program`](event-program/) | A program without registration: one Questionnaire, one occurrence date, no enrollment | EPI Stock, Antenatal care visit, ANC follow-up; Pujehun |
| [`tracker-registration`](tracker-registration/) | Registering a person, enrolling them, and answering two stage forms | EPI Stock, Supervision visit, Child Programme; Koinadugu |
| [`terminology-strict`](terminology-strict/) | Concept codes taken from DHIS2 codes rather than DHIS2 UIDs, and what that trades | EPI Stock, Supervision visit, ANC follow-up; Kambia |
| [`registry-district`](registry-district/) | One district's organisation units as Organization and Location pairs, boundaries and all | EPI Stock, Supervision visit, ANC follow-up; Bonthe |
| [`facility-mixed`](facility-mixed/) | One of every capture kind at once - the flagship | EPI Stock, Antenatal care visit, Child Programme; Koinadugu |
| [`patient-summary`](patient-summary/) | An International Patient Summary at `$summary`: who a person is, which recorded values are doses, and what the document says about itself | EPI Stock, Supervision visit, Child Programme; Koinadugu |
| [`refused-names`](refused-names/) | The exhibit: a selection `d2w fhir generate` refuses, and why refusing in seconds beats failing in hours | Child Health, Supervision visit, ANC follow-up; Kambia |

## Which of these `d2w fhir init --template` scaffolds from

An example is a template only when it declares itself one. Every guide here
carries a `template.toml` beside its `fhir.toml`, and that file is the whole
declaration:

```toml
scaffolds = true
summary = "The smallest complete guide: the forms, one district, no category axes."
```

`summary` is the row `d2w fhir init --list-templates` prints for the guide, so
the listing names what the catalog says rather than what a page once said.

[`refused-names`](refused-names/) declares the other side:

```toml
scaffolds = false
refusal = """
It demonstrates the names `d2w fhir generate` refuses: ..."""
```

It is the exhibit, not a guide: the run is refused on the first hostile name,
which leaves the foundation target on disk and nothing after it, so it carries no
generated tree to lay down and `make sushi` has nothing it can compile.
`--list-templates` leaves it out, and `d2w fhir init x --template refused-names`
prints that `refusal` instead of scaffolding a project it would then tell you to
compile.

Three of the eight templates also ride the installed wheel, as payloads under
`packages/dhis2w-fhir/src/dhis2w_fhir/scaffold/projects/`; the manifest beside
them names those three plus the five that scaffold from a checkout alone, and
`test_fhir_init_templates.py` fails when that manifest and these declarations
disagree.

## The identity scheme

Every guide is scaffolded with the same shape, so a reader comparing two of them
is comparing their content rather than their names:

| Field | Value |
| --- | --- |
| `--id` | `dhis2.fhir.examples.<directory name>` |
| `--canonical` | `http://example.org/fhir/examples/<directory name>` |
| `--name` | `Examples` plus the directory name in PascalCase |
| `--title` | A sentence naming the story, e.g. `Minimal aggregate example guide` |
| `--publisher` | `dhis2w examples` |
| `--publisher-url` | Not set. The IG publisher links it from every page, and a URL that is not a real site is one broken link per page |
| `--status` | `draft` - these are examples, not published guides |
| `--profile` | `local_basic`, the seeded local stack |
| `--sushi-timeout` | The scaffold default |

`example.org` is the IANA-reserved documentation domain, so no canonical here
can ever collide with a real guide.

## What every guide selects, and why it has to

Three things are true of every `fhir.toml` in this catalog, and they are the
same three every time:

**An absent selection table means everything.** `[generate.data_sets]`,
`[generate.event_programs]`, `[generate.tracker_programs]`,
`[generate.option_sets]`, and `[generate.categories]` each cover the whole
instance when they are absent or empty, and there is no way to select none of a
kind. So every guide here names all five, and every guide carries one aggregate
form, one event form, and one tracker program's forms. What differs between
guides is which ones, and how they are configured.

**The seeded instance carries deliberately template-hostile metadata.** Option
set `Age (<5 - 49) & over` (`OsFhirEscS1`) and category `Age (<5 >5) & sex`
(`CatFhirEsc1`) exist to exercise exactly the gate the exhibit demonstrates. They
belong to no form, so naming vocabularies explicitly is what keeps them out - a
guide that left `[generate.option_sets]` absent would be refused before it wrote
a file. [`refused-names`](refused-names/) is the one that lets that happen.

**One district, level 4.** Every form on this instance is assigned at level 4, so
a registry that stops higher publishes no unit any form reports at.
`[generate.organisation_units] root` narrows the tree to a single district and
`max_level = 4` takes it to the facilities - 68 to 82 units per guide, published
as an Organization and a Location each. A guide covering the whole country would
publish 1332 of them, which is the difference between a compile of seconds and
one of many minutes.

## The Python project, and the lock

`d2w fhir init` writes a `pyproject.toml`: a scaffolded project is a `uv` project
whose lock pins the exact d2w build that generated it. Both decisions here follow
from that, and neither is the scaffold's fault:

- **`pyproject.toml` is committed.** It is part of what `init` writes, and a
  reader browsing a tree here should see the whole tree. The workspace ignores
  it: `[tool.uv.workspace] members` is the explicit `packages/*` list, so a
  `pyproject.toml` under `examples/` is not a workspace member and nothing
  resolves it.
- **`uv.lock` is not committed, and never written.** The catalog drives every
  guide through the workspace `d2w`, never through a project environment of its
  own, so no guide here has ever been `uv sync`ed. A per-guide lock would pin the
  same commit nine times and go stale nine times. A real project you scaffold
  from these does commit its lock - [Set up an IG
  project](../../../docs/fhir/201-set-up-a-project.md#install-the-pinned-toolchain)
  says why.

## The refresh doctrine

**These trees are scaffold-managed.** Every file but `fhir.toml`, `template.toml`
and the two hand-authored stubs (`ig/input/fsh/aliases.fsh`,
`ig/input/pagecontent/index.md`) is what `d2w fhir init` writes today, byte for
byte. When the scaffold gains a
line - a new `path-resource` glob, a new `.gitignore` entry, a new menu item -
one command brings all nine up to date:

```bash
for guide in examples/fhir/igs/*/; do uv run d2w fhir init "$guide" --refresh; done
```

`make verify-igs` asserts there is nothing to bring: its first step per guide is
a refresh, and it fails when the refresh creates, rewrites, or keeps a file. So a
scaffold change that these trees have not taken up is a red build, not a silent
drift.

`fhir.toml` is never written by a refresh, which is what makes the hand-edited
block at the bottom of each one safe. Each guide's README states which lines were
added by hand and why.

## Generated output is not committed

`d2w fhir generate` writes FSH under `ig/input/fsh/`, pre-built JSON under
`ig/input/resources/`, and markdown under `ig/input/pagecontent/`; SUSHI writes
`ig/fsh-generated/`; validate writes `reports/`. Each project's own `.gitignore`
covers the JSON, the build output, and the reports, because a real project does
not commit those either. [`.gitignore`](.gitignore) beside this file covers the
two a real project *does* commit - the generated FSH and the generated pages -
because this catalog holds inputs and regenerates the rest.

`git status --porcelain` is empty after `make verify-igs`. That is the check.

## How `make verify-igs` runs

From the repository root, with the seeded stack up:

```bash
make dhis2-run          # in another terminal, if it is not already running
make verify-igs
```

Per guide, in order:

1. **refresh** - `d2w fhir init <dir> --refresh` must report nothing to write.
2. **validate** - `d2w fhir validate --no-fail`, and the counts are recorded.
   Every guide but the exhibit must carry no error on its own build path; the
   exhibit must carry at least one `template-hostile-name` error.
3. **generate** - `d2w fhir generate`. Every guide but the exhibit must succeed;
   the exhibit must be refused, naming the object it refused on.
4. **compile** - the project's own `make sushi`, which is SUSHI in docker. Every
   guide skips it when docker is not available, with that stated as the reason.
   The exhibit compiles nothing and is read instead on what its refused run left:
   `aliases.fsh` and the foundation target under `ig/input/fsh/`, nothing after
   them, and no compile beside them.

The runner is [`infra/scripts/verify_igs.py`](../../../infra/scripts/verify_igs.py).
It is an on-demand target: it needs a reachable DHIS2 instance and docker, so it
is not part of `make test` and not part of the default CI run. `--only <guide>`
narrows it to one, and `--no-compile` drops the docker step.

The full IG publisher - `make build` inside a project - is not part of this. It
takes hours per guide, and what it would add over SUSHI is rendered pages rather
than resources.

## Regenerating every guide

Nothing under `ig/input/fsh/` or `ig/input/pagecontent/` is committed, so there is
no such thing as a guide here that has fallen behind an emitter: the tree a reader
compiles is the tree the current build writes. What does fall behind is a
selection - a `fhir.toml` naming a UID the seeded instance no longer carries - and
that is what regenerating catches. Four commands, from the repository root:

```bash
make dhis2-run DHIS2_VERSION=v43   # the seeded stack, in another terminal
make verify-igs                    # refresh, validate, generate, compile, all nine
git status --porcelain             # empty, or a committed input has moved
make clean-artifacts               # sweep the regenerated trees back off disk
```

`make dhis2-run` restores the prebuilt dump, so it is minutes rather than the
hours a full reseed takes; [`docs/local-setup.md`](../../../docs/local-setup.md)
covers rebuilding that dump. Every UID a `fhir.toml` here names belongs to that
dump, so `play.dhis2.org` is not a substitute: run the catalog against the local
stack or not at all.

The regenerated trees are git-ignored, not absent - a checkout that has run the
catalog holds every generated file on disk until `make clean-artifacts` sweeps
them. A tree left there is a tree the next reader takes for a committed one, so
sweep it before reading anything under a guide as what the catalog ships.

## Building one by hand

```bash
export DHIS2_PROFILE=local_basic
cd examples/fhir/igs/facility-mixed

uv run --project ../../../.. d2w fhir validate    # what the instance costs this guide
uv run --project ../../../.. d2w fhir generate    # the IG source, from the instance
make setup                                        # the SUSHI + IG publisher image, once
make sushi                                        # compile the FSH
```

`uv run --project ../../../..` is what makes the workspace build of `d2w` run
inside a directory that is itself a `uv` project. `make clean` inside a guide
removes everything those two steps wrote.
