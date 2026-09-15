# Build and publish the guide

Generation wrote source files. This step turns them into the thing you hand
over: a static website that documents every data set, program, option set,
and organisation unit the last step read out of your instance, one browsable
page each, with every code and identifier resolvable. It runs in Docker, and
it is the only step in this series with a real machine cost - everything
before it is quick by comparison - so most of this page is about paying that
cost once rather than every time you change something.

**Who this is for:** the operator turning generated source into the
browsable, publishable site - and keeping the build fast.

**Before you start:** a generated project ([Generate the IG
source](201-generate.md)), Docker running, and network access to a FHIR
terminology server (or a plan for offline, below).

**You will be able to:**

- compile the FSH as a fast gate, and run the full publisher when it counts
- refuse a build in seconds that would otherwise have failed in hours
- size the build - what the registry costs, what the caches buy back
- read the publisher's exit codes instead of guessing

## Build it

Both tools live in the scaffolded Docker image, so neither SUSHI, the IG
publisher, nor Java is installed on your machine. Build it once, and make the
shared package-cache volume writable by the publisher's non-root user while you
are there - a freshly created volume is root-owned:

```bash
docker build -t fhir-ig .

docker run --rm -u root -v fhir-ig-cache:/home/publisher/.fhir --entrypoint sh fhir-ig \
    -c "mkdir -p /home/publisher/.fhir/packages && chown -R 1001:1001 /home/publisher/.fhir"
```

Then there are two ways to run the toolchain over `ig/` - SUSHI alone as a fast
gate, or the full publisher:

```bash
# fast gate: compile FSH to FHIR resources, no site
docker run --rm -v $(pwd)/ig:/home/publisher/ig -v fhir-ig-cache:/home/publisher/.fhir \
    fhir-ig sushi .

# the full publisher; the site lands in ig/output/
docker run --rm -v $(pwd)/ig:/home/publisher/ig -v fhir-ig-cache:/home/publisher/.fhir \
    fhir-ig \
    java -Xmx8g -jar /home/publisher/.ig-publisher/publisher.jar ig.ini -ig . -tx http://tx.fhir.org
```

SUSHI alone is the one you run in a loop. It compiles and says whether the
source is valid, in a fraction of what a published site costs:

```console
$ docker run --rm -v $(pwd)/ig:/home/publisher/ig -v fhir-ig-cache:/home/publisher/.fhir fhir-ig sushi .
info  Loaded virtual package sushi-local#LOCAL with 2728 resources
info  Converting FSH to FHIR resources...
info  Converted 27 FHIR StructureDefinitions.
info  Converted 7 FHIR CodeSystems.
info  Converted 7 FHIR ValueSets.
info  Converted 60 FHIR instances.
info  Exporting FHIR resources as JSON...
info  Exported 101 FHIR resources as JSON.
info  Assembling Implementation Guide sources...
info  Assembled Implementation Guide sources; ready for IG Publisher.

========================= SUSHI RESULTS ===========================
| Swish! Nothing but fishnet.            0 Errors      0 Warnings |
===================================================================
```

The 2,728 loaded resources against 101 exported ones is the shape of the
whole project: the registry and the terminology ship as pre-built JSON that
SUSHI loads and passes through, and only the forms and the definitional
layer are compiled from source.

The scaffold's Makefile wraps every command on this page - `setup`, `sushi`,
and `build` are the lines above, with the chown folded in as a prerequisite
and the JVM heap derived into a `JAVA_HEAP` variable, and `generate` /
`validate` are `uv run d2w fhir generate` / `... validate`. `build` runs one
thing the lines above do not: the artifact scan below, which refuses a doomed
publisher run before it starts. [Set up an IG
project](201-set-up-a-project.md) lists the targets. Only `refresh` does
something no single command above does: it chains clean-all, upgrade,
generate, validate, and build, tolerating validate's exit 1 so a full rebuild
still produces fresh reports, and it deliberately skips SUSHI because the
publisher runs its own over the same FSH.

`d2w fhir generate` and `d2w fhir validate` normally run as `uv run d2w` -
the toolchain `uv.lock` pinned. To drive a checkout or a git ref instead,
spell the source into the command:

```bash
# From a local checkout of dhis2w:
uv run --project /path/to/dhis2w d2w fhir generate

# Straight from a git ref, nothing installed, no uv sync:
uvx --from 'git+ssh://git@github.com/winterop-com/dhis2w.git@main#subdirectory=packages/dhis2w-cli' \
    --with 'dhis2w-fhir @ git+ssh://git@github.com/winterop-com/dhis2w.git@main#subdirectory=packages/dhis2w-fhir' \
    d2w fhir generate
```

!!! warning "Do not iterate on the publisher"
    `d2w fhir generate` followed by the SUSHI-only run compiles the FSH and
    tells you whether it is valid without paying for a published site. Run the
    publisher when you are ready to publish one, not after every edit.

## The build refuses before it begins

`make build` does not go straight to the publisher. Its first line is
`d2w fhir check-artifacts`, a scan of the files on disk for the one thing the
publisher cannot survive: a raw `<` in a DHIS2 name or code. That character
survives every earlier pass, the publisher's own Checking Output HTML step
included, and kills the final AI-markdown pass - hours in, once every resource
has already been rendered, with a message naming a page rather than the object.
[Troubleshooting](201-troubleshooting.md#sushi-and-ig-publisher-failures)
carries that stack trace.

Generation already refuses such a selection. The scan exists because a build
does not read a selection - it publishes whatever `ig/fsh-generated/` and
`ig/input/` hold. Output written before the gate existed, output from an older
toolchain pin, and hand-authored FSH all reach the publisher without ever
passing it.

It reads the guide's own identity as well - `title`, `name`, `publisher` and
`description`, in `fhir.toml`'s `[ig]` table and in `ig/sushi-config.yaml`. No
DHIS2 selection supplies those, and no compiled resource carries them until
SUSHI has run, so on a project that has only run `d2w fhir generate` there is
nowhere else on disk for a title carrying a `<` to be found - and the publisher
dies on it in the very same last pass. One identity stated in both files is one
finding, named at `fhir.toml`, which is where `d2w fhir init --refresh` writes
the other from.

The scan catches one more build-stopper, for a guide that depends on an
[organisation-unit registry package](201-registry-package.md): a reference to a
unit that package does not publish. It compares the references already on disk
against what the registry carries, so two projects whose selections have drifted
apart are named here in seconds rather than by the publisher after it has
rendered everything else. Like the rest of the scan it reads no instance; when
no checkout answers, name the archive with `--registry-package`.

The recipe asks the CLI's own help before running the scan. A project whose
lock pins a dhis2w-fhir without the command (before 1.8) gets a warning that
names the upgrade (`uv lock --upgrade && uv sync`) and a build that proceeds
unscanned - a missing preflight must never stop a publishable guide.

It reads the same files the publisher reads, through the very predicates the
generate-time refusal uses, and it opens no connection and reads no profile -
so it answers in seconds, offline, on any project:

```console
$ d2w fhir check-artifacts
                        fhir check-artifacts
┌──────────────┬─────────────────────────────────────────────┐
│project       │ /home/you/anc-guide                         │
│json files    │ 240                                         │
│fsh files     │ 42                                          │
│build-aborting│ 0                                           │
│warnings      │ 0                                           │
└──────────────┴─────────────────────────────────────────────┘
ok: 282 publishable file(s) scanned; nothing the IG publisher aborts on
```

A stale artifact turns that into a refusal that names the file, the resource,
the element, and the value - three findings here, from one CodeSystem an old
generate wrote:

```console
$ d2w fhir check-artifacts
                        fhir check-artifacts
┌──────────────┬─────────────────────────────────────────────┐
│project       │ /home/you/anc-guide                         │
│json files    │ 240                                         │
│fsh files     │ 42                                          │
│build-aborting│ 3                                           │
│warnings      │ 0                                           │
└──────────────┴─────────────────────────────────────────────┘
                            artifact findings (3)
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┓
┃Severity       ┃ File                     ┃ Resource  ┃ Field               ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━┩
│build-aborting │ ...System-d2-os-Age.json │ d2-os-Age │ concept[0].display  │
│build-aborting │ ...System-d2-os-Age.json │ d2-os-Age │ identifier[0].value │
│build-aborting │ ...System-d2-os-Age.json │ d2-os-Age │ title               │
└───────────────┴──────────────────────────┴───────────┴─────────────────────┘
note: what to do: Rename it in DHIS2 or narrow the selection in fhir.toml, then
run `d2w fhir generate` again.
note: what it costs: a name carrying '<' stays byte-true on the resource, and
the IG publisher writes it into pages it strict-parses after writing, so `make
build` aborts in its last pass, once every resource has already been rendered.
error: 3 build-aborting artifact(s) found; exiting 1 before the publisher runs
(--no-fail to suppress)

$ echo $?
1
```

Each row also carries the offending value, in a `Value` column left out above
for width. The table is written to read at eighty columns, which is what a CI
log gets: the path is cut from the front so the end that names the file
survives, and the resource and the element come out in that order on a terminal
too narrow for them - both are in `--json`.

The line that answers a finding is printed under the table rather than in a
column, once per distinct remedy: six sentences stand behind every finding the
scan raises, and a column would print one of the six once per row. Which line a
finding gets follows from where the value came from, which the finding records
rather than the printer guessing:

| The value came from | What the finding asks for |
| --- | --- |
| DHIS2, through a generated artifact | a rename in DHIS2 or a narrower `fhir.toml` selection, then another `d2w fhir generate` |
| the `[ig]` table of `fhir.toml` | that key changed there, then `d2w fhir init --refresh` |
| a hand-authored FSH source | an edit of the file, because no regeneration rewrites one |
| a registry package the guide depends on | both projects regenerated against the same instance |

`--json` puts the whole typed report on stdout.

### The findings the build survives

A published Questionnaire whose organisation-unit assignment `List` names no
unit this project publishes is a `warning` rather than a refusal. That guide
compiles, publishes, and renders; what it does not have is anywhere for that
form to be submitted from, so [`$generate` answers 422](201-serve.md) and DHIS2
would refuse the capture with `E1029`. The command still exits 0 - `make build`
runs it to refuse a doomed publisher run, and this build is not doomed - and the
finding names the form, the List it points at, and the way out:

```console
$ d2w fhir check-artifacts
...
warning: 29 finding(s) the build survives; the guide publishes and what it costs
is read in the table above

$ echo $?
0
```

The usual cause is `[generate.organisation_units] max_level` set above the level
the forms are assigned at; `d2w fhir generate` says the same thing at the end of
its own run. [Set up a project](201-set-up-a-project.md#choosing-a-max-level)
carries that trade-off.

The second survivable finding is the same loss one axis over. A form binding an
attribute-combo vocabulary whose every concept is scoped away from every
organisation unit this project publishes is a form nobody may file a capture
for: DHIS2 refuses one keyed to any of those combos with `E8025`. The scan reads
it off the published restriction `List`s alone - a concept names one `List` per
restricted category option it is met from, and it is usable only where every one
of them holds the organisation unit - so no connection is needed, and the
finding carries the same two dials as the assignment one.

The third is the same loss one axis further over. A category option is scoped to
a calendar window as well, and DHIS2 refuses a capture the window does not cover
entirely with `E8032`, so a form binding a vocabulary whose every concept closed
before the period the form reports now is a form nobody may file a capture for.
The scan reads it off the shipped bytes alone - the `dhis2-valid-from` /
`dhis2-valid-to` properties each concept carries, and the DHIS2 period type the
Questionnaire declares - so no connection is needed here either. Its line names
no `fhir.toml` dial, because none reaches it: a category option's `startDate` and
`endDate` are DHIS2 metadata, so the options are reopened in DHIS2 or the form
selection is narrowed.

The fourth is a `[generate.*] include_ids` entry the published tree carries no
trace of: the UID names no object on the instance the guide was generated
against, so the guide publishes without that form, its examples, and its page.
The selection is graded only against a tree a run finished writing. A refused
run - `hostile_names = "refuse"` meeting a DHIS2 name carrying `<` - writes the
foundation target and stops, and reading a selection off that half-written tree
would say a UID live on the instance is not on it, when that very object is what
the run refused over. The pages are the evidence the run reached the end: they
narrate what every other target wrote, so they are the last thing a run writes,
and one page under `ig/input/pagecontent/` carrying the generated header is a
tree every entry may be read off. Without one the scan says the run did not
complete and grades nothing.

The fifth is a published example answering a question the form's own
`D2ProgramRule` extension says DHIS2 computes. A rule whose action is `#ASSIGN`
names each question it computes on an `assigns` sub-extension; DHIS2 calculates
that value on import and refuses a payload whose answer is neither empty nor
byte-equal to it, with `E1307`. `d2w fhir generate` leaves every such question
unanswered, so a finding here is a hand-authored example, or a tree an older
run wrote. Both formats an example lives in are read - the compiled JSON, and
the FSH source it was compiled from, which is the only place a hand-authored
example sits, the file the remedy sends you to, and the only half of the tree a
project holds before `make build` has run SUSHI. The forms are read in both
formats for the same reason: a project before its first compile states the
questions its rules compute on the FSH Questionnaire's own `assigns` slice, so
the scan answers there too:

```console
$ d2w fhir check-artifacts
...
warning  computed-answer  QuestionnaireResponse  eBAyeGv0exc-example-1  ySU9WWHNoVG  1
```

The guide builds and publishes either way; what the finding costs is an example
nobody can import.

The scan covers three trees, and each position it reads is one the emitted
resource carries byte-true into a page:

| Read | Positions | Where the publisher would have died |
| --- | --- | --- |
| `ig/fsh-generated/**/*.json` | `name`, `title`, `display`, `text`, `identifier[].value` | the compiled resources it renders a page each from |
| `ig/input/resources/**/*.json` | the same five | the registry, terminology, and ConceptMap documents SUSHI passes through untouched |
| `ig/input/fsh/**/*.fsh` | `Title:`, assignments to those elements, `* #code "display"` rules | the FSH sources, generated and hand-authored alike |
| `fhir.toml` | `[ig]` `title`, `name`, `publisher` | the ImplementationGuide resource and every page rendered from it |
| `ig/sushi-config.yaml` | `title`, `name`, `publisher`, `description` | the same, on a project whose sushi-config was edited away from `fhir.toml` |

`ig/input/pagecontent/**/*.md` is deliberately left out: markdown carries HTML
by design, so a `<` there is the page's own markup.

An existing project takes the gate up with one command - `d2w fhir init
--refresh` adds the `check` target and the line that runs it, and never
rewrites anything else in the Makefile:

```bash
d2w fhir init --refresh
make build
```

## Turn the three build knobs

The scaffold sets all three, the first two because the defaults break on a
real instance's IG.

**The SUSHI timeout** - `ig/fsh.ini` raises it to 1800 seconds, settable at
scaffold time with `d2w fhir init --sushi-timeout`. The IG publisher re-runs
SUSHI internally with a 300-second default, which the FSH of a real
instance's IG overruns easily; the publisher then dies with exit 143 in its
very first phase:

```text
Sushi timeout exceeded: 1800 seconds
Exception: Process exited with an error: 143 (Exit value: 143)
```

**`TX_SERVER`** picks the terminology server the publisher validates
against; it defaults to `http://tx.fhir.org`. `TX_SERVER=n/a` disables
terminology validation for an offline build, and a generated guide does
build that way - a district registry in 51 seconds, site and all. What it
costs is one error per organisation unit carrying geometry: the GeoJSON
boundary attachment states its media type, that field binds to the IETF BCP
13 media types, and only a terminology server can answer that value set.
Those errors are the whole difference, and they go away online.

**`JAVA_HEAP`** is the publisher's JVM heap ceiling, and the Makefile sizes it
to the machine rather than writing a number down: the memory docker reports,
less 2 GB, floored at `4g`, capped at `31g`, and falling back to `8g` when
docker cannot be asked. A literal would be wrong somewhere either way - too
small for a national registry on a workstation, too large to survive on a
laptop - and docker knows what it has. Every build states what it derived:

```text
publisher heap 22g, docker memory 24.0 GB
```

The daemon is asked once per build, on first use, so `help`, `clean` and
`generate` never wake it and the banner, the `-Xmx` and the kill report all
quote one answer.

Two things about that figure are worth knowing. `docker info --format
'{{.MemTotal}}'` is the VM Docker Desktop runs on macOS and Windows, and the
whole machine's RAM on Linux - where the derivation sees everything the host
has, whatever else is running on it. That is why CI pins `JAVA_HEAP: 4g` rather
than deriving: a shared build host would hand the publisher a ceiling sized to
a machine it does not have to itself. And `31g` is the top wherever the number
comes from, because the JVM drops compressed object pointers above roughly
32 GB and the same live set suddenly costs materially more heap; the largest
guide measured here peaked at 16.

It is a ceiling, not a reservation: a guide that needs less simply uses less.
Set it yourself on the command line or in the environment whenever you want a
particular ceiling, and the value outlives a refresh:

```bash
make build JAVA_HEAP=8g
```

An empty `JAVA_HEAP` - a CI wrapper with an unset variable, `JAVA_HEAP= make
build` - derives exactly as an unset one does, rather than handing the
publisher a bare `-Xmx`.

### The two ways memory fails

They look alike and need opposite fixes, so read which one you have before
turning a knob.

**Killed** - the ceiling is too large for the box:

```text
Generating Summary Outputs (en)
make: *** [build] Error 137
```

137 is `128 + 9`, SIGKILL. `ig/output` holds whatever the last completed build
wrote, or is partial: the publisher writes the site in one pass at the very end,
so nothing from a killed run is trustworthy. The container reads its own
cgroup's `oom_kill` count as it exits, and a non-zero one is what makes the
build say this was the kernel's out-of-memory killer rather than a `docker
stop`, a `docker kill`, or a timeout around the build - all of which exit 137
too, and get a shorter message saying so. The out-of-memory report names the
ceiling, the memory docker reports, the peak the container actually reached,
and the containers running when it was sampled. The publisher and Jekyll share
one container and Jekyll renders while the JVM is still resident, which is why
kills land in the last phase and why stopping everything else is the first
thing to try.

**Out of memory** - the ceiling is too small for the guide:

```text
Exception in thread "main" java.lang.OutOfMemoryError: Java heap space
```

A Java stack trace, a different exit code, partial output on disk. This is a
real build error, not a kill, and the fix is the opposite one: more heap.

Confirm a suspected kill by dropping `--rm` from the run and then
`docker inspect <container> --format '{{.State.OOMKilled}}'`.

### What that costs in practice

The two failures squeeze against each other, and the 2 GB the derivation keeps
back is a deliberately generous setting of that squeeze. A publisher build is a
monthly act: give it the machine, stop the other containers, and let the kill
report be the safety net on the rare run where that was not enough. An 8 GB heap
needs roughly 10 GB of room once metaspace, JVM native memory and the OS are
counted, and the 2 GB is what covers the difference on a machine doing nothing
else.

On a machine that is too small for its guide, the squeeze is tight enough that
the first run can be killed. Measured on one 16 GB docker VM against one
national guide: `4g` dies in validation, `10g` clears validation and is then
OOM-killed at Jekyll, and `8g` completes the whole build - about 21 minutes,
site, package, and QA report. The derivation would hand that VM `14g`, which is
inside that kill range: the first build reports the kill, names the peak the
container reached, and `make build JAVA_HEAP=8g` is the answer it points at.

Measured on a national instance publishing all five levels - 12,581
organisation units, 25,162 instances - the registry package peaked at 14-16 GB
and the guide depending on it at 9.3-9.7 GB. A build at that scale needs docker
sized accordingly, and the derivation will hand it whatever docker reports, up
to the `31g` cap.

To run the publisher by hand with a heap of your own choosing:

```bash
# bytes of memory available to docker
docker info --format '{{.MemTotal}}'

docker run --rm -v $(pwd)/ig:/home/publisher/ig -v fhir-ig-cache:/home/publisher/.fhir \
    fhir-ig \
    java -Xmx2g -jar /home/publisher/.ig-publisher/publisher.jar ig.ini -ig . -tx http://tx.fhir.org
```

## Size the build

The counts below were taken from real instances (the Sierra Leone demo:
171 option sets, 2,664 registry instances, 3,101 resources; the uncapped
a national instance: 235 option sets, 25,162 registry instances). Counts
travel between machines; the wall clock they cost does not, so this section
talks about what is expensive relative to what.

Generation is the cheap half; the toolchain is where the time goes. On the
demo, `generate` and `validate` are both quick; a national instance takes
several minutes to generate and still costs a small fraction of a build.

**The registry is usually the largest thing in the IG by a wide margin** -
every unit emits an Organization and a Location, and a hierarchy fans out at
the bottom:

| Level | Units | Instances |
| --- | --- | --- |
| 1 | 2 | 4 |
| 2 | 33 | 66 |
| 3 | 447 | 894 |
| 4 | 1,867 | 3,734 |
| 5 | 10,232 | 20,464 |
| **total** | **12,581** | **25,162** |

Level 5 alone is 81% of that registry. The registry ships as pre-built JSON
SUSHI never compiles, but the publisher writes and renders a page per
resource - so the registry sets the wall clock of the publisher run, and
`[generate.organisation_units]` `max_level` / `root` is the lever on the
*published* size (25,162 instances down to 4,698 with `max_level = 4`), not
on the compile.

**What the compile costs** - running SUSHI on its own, with no publisher and
no timeout, isolates the compile. What it buys is the FSH: the forms and five
compiled CodeSystems, dominated by the two data-dictionary files (2.5MB of
FSH on an uncapped national IG). Writing that instance's 235 option sets as FSH
instead of predefined JSON makes the compile roughly half again as long,
which is the case for predefined terminology; fewer selected forms mean
smaller dictionary files. Docker is not where the compile's time goes - the
mount is a rounding error against it, and running SUSHI natively rather than
containerised saves on the order of a fifth. The rest is SUSHI's own work.
The publisher run is the other story entirely, and the section below is it.

**What the publisher pays for** is sheer resource count - every format it
writes and every page it renders is per resource - which is why the
scaffolded `sushi-config.yaml` excludes what a DHIS2-derived guide's
consumers never read: the XML and Turtle wire formats (`excludexml`,
`excludettl` - on the demo, half the output: 13,710 files and 466MB instead
of 26,120 and 874MB). The per-resource spreadsheet pass is not worth
excluding and there is no parameter for it anyway: the publisher knows no
`excludexls`, and on a national guide the pass it looks like it would skip
runs in under two seconds.

Terminology service time is a fixed cost only while the cache is warm: a
cold cache on a large guide pays `TX_SERVER` a round-trip per coding, which
can dominate everything else - and is why the caches survive a
`make refresh`.

## Why a build is fast now

A build that used to run for a long stretch was mostly not running. Two of
its longest phases were waiting, and a third was writing through a mount.
All three are handled by what `d2w fhir generate` emits and what
`d2w fhir init --refresh` writes, so a current project pays none of them.
The numbers below are one district-scale guide, measured phase by phase off
the publisher's own log.

**The terminology wait.** A DHIS2 identifier namespace -
`http://dhis2.org/fhir/id/option`, and five siblings - is declared as a
NamingSystem, which says the URL identifies DHIS2 objects and lists nothing.
Every ConceptMap row is validated against the system its target code sits
in, and a NamingSystem answers no `$validate-code`, so the publisher asked
the terminology server about each row on its own and was told
UNKNOWN_CODESYSTEM each time: **4,779 requests**, 57 percent of them byte-for-byte
repeats, with the narrative phase alone at **438 seconds**. Generation now
publishes each of those namespaces a second time, as a CodeSystem at the
same URL with `content: complete` and every identifier the guide's maps name
enumerated in it. The publisher answers the question out of the guide:
**5 requests, and narratives in 1.5 seconds**. (`content: not-present` does not
work - the publisher reads it as "the codes are elsewhere" and asks the
server anyway.)

Each of those CodeSystems is published at a URL outside the IG's own
canonical, which the publisher calls a mismatch unless the URL is declared.
The scaffolded `sushi-config.yaml` declares all six under `special-url`;
they follow `[generate] identifier_system_base`, so a project that changes
that key changes those six lines with it.

**The mount.** Docker on macOS reaches a host directory over a network-style
filesystem, and the publisher's output phase writes tens of thousands of
small files one at a time. That single phase took **341 seconds** through the
mount and **21 seconds** on the container's own disk. `make build` now streams
the project into the container, builds it there, and streams `output/`,
`fsh-generated/` and `input-cache/` back - two bulk copies instead of one
file at a time. `temp/` and `template/` stay behind; nothing reads them and
they are the bulk of what a build writes. `make build-bind` is the old
behaviour, worth reaching for when you want to watch `output/` fill up as it
is written.

**Offline builds work.** `make build TX_SERVER=n/a` completes - site, QA
report and all - in **51 seconds** on that guide. The section above says what it
costs.

## Keep the caches warm

Most of what a repeat build would re-pay is cached, and the scaffold wires
both up:

- **The FHIR package cache** is the named docker volume `fhir-ig-cache`,
  mounted at `~/.fhir` in the container by both runs above - which is why
  both need the chown, a fresh volume being root-owned and the publisher's
  user not. Without the volume, every run re-downloads the core packages
  before it can start, and on a slow link that download alone can rival the
  build.
- **The terminology cache** is `ig/input-cache/`, written by the publisher
  and ignored by git. Leave it in place when you clear build output; a warm
  tx cache takes the validation phase from minutes to seconds.

Both caches survive `make clean` and `make refresh` - a refresh pulls new
tooling and regenerates, neither of which invalidates a cache keyed by what
it holds. `make clean-all` is the deliberate wipe, and running it before a
build is how you reproduce a cold one. The package cache volume is named
`fhir-ig-cache` in every scaffolded project, so it is one cache shared by every
guide on the machine: a `make clean-all` in one project makes the next build of
each of them cold, and a project whose `clean-all` finds the volume already gone
says so and carries on.

## Publish it

The generated site lands in `ig/output/` - plain static files. Publish them
however your organisation hosts static sites; the canonical URL you
scaffolded with is where consumers will expect to find it. Before handing
it over, read `ig/output/qa.html` - the publisher's own QA summary of
errors, warnings, and broken links.

## The weekly publisher check

HL7 ships a new `publisher.jar` often, and a release that tightens validation
turns a guide that built yesterday into a guide that does not. `make verify-igs`
does not catch that: it compiles the example catalog with dockerized SUSHI, and
SUSHI is not the pass that gets stricter. So the repository runs one full
publisher build a week, in `.github/workflows/publisher-check.yml`.

It scaffolds `aggregate-minimal` from its bundled template - the smallest
complete guide, already generated against a DHIS2 instance, so no instance is
needed - builds the image against whatever `publisher.jar` HL7 ships that day,
compiles the FSH, and runs the publisher with a 4g heap against
`http://tx.fhir.org`. The job fails when `ig/output/qa.json` reports any error,
and prints the publisher version, the counts, and the error lines of `qa.txt`
grouped by message shape, so a tightened rule reads as one family of sixty
rather than sixty separate lines. The same summary runs over a local build:

```bash
make publisher-check-summary QA=ig/output/qa.json
```

Sundays 03:00 UTC on the schedule, and by hand whenever a publisher release
looks worth testing early:

```bash
gh workflow run publisher-check.yml -f guide=aggregate-minimal
```

The `guide` input takes any bundled template - `aggregate-minimal`,
`event-program`, `patient-summary` - since only those carry the generated FSH a
build needs without a DHIS2 instance to generate it from.

Next: [Serve the guide](201-serve.md) - the compiled guide, answered live as a
FHIR endpoint.
