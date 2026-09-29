# Build a registry and a guide

This page takes one DHIS2 instance to two built FHIR implementation guides that
work together:

- a **registry package** publishing the organisation unit hierarchy, one
  `Organization` and one `Location` per organisation unit;
- a **guide** publishing the forms - data sets, event programs, tracker
  programs - which depends on the registry for every organisation unit its forms
  are reported from.

It is the path to follow for a national instance. Every step is a command you
run, and each step names what to check before you move to the next one, because
a mistake made at step 2 costs a whole build to find at step 7. For why the
registry is split out at all, and what the guide reads out of the package, see
[Publish the registry as a package](201-registry-package.md).

## Before you start

**A profile for the instance.** Every command reads DHIS2 through a profile:

```bash
d2w profile add national --url https://dhis2.example.org --auth basic --username admin
d2w -p national system info
```

**Docker with room for the build.** The IG publisher runs in a container. On a
registry of about twelve thousand organisation units, a build holds roughly
14 GB while it writes the site. Give Docker 20 GB or more, and check what it
has:

```bash
docker info --format '{{.MemTotal}}'
```

On Docker Desktop that is the Docker VM's memory (Settings > Resources >
Memory); on Linux it is the machine's. Stop other containers - a local DHIS2
especially - before you build.

## 1. Find the root organisation unit

An instance often has more than one top-level organisation unit. One is the
country; another may hold deactivated or test organisation units that nobody
means to publish.

```bash
d2w -p national metadata list organisationUnits --filter level:eq:1 --fields id,name
```

On an instance where retired organisation units are moved under a second root,
this lists two rows: the country, and something like "Deactivated
organisation units". Note the country's UID, and decide how deep to publish. The deepest level is
usually most of the organisation units, and so most of the build.

## 2. Scaffold both projects

```bash
d2w fhir init national --with-registry \
    --id dhis2.fhir.national \
    --canonical http://fhir.example.org/national \
    --profile national \
    --org-unit-root ImspTQPwCqd \
    --org-unit-max-level 5
```

This writes `national/registry/` and `national/guide/`, wired to each other.
The registry's id and canonical are derived from the guide's
(`dhis2.fhir.national.registry`, `http://fhir.example.org/national/registry`),
so the values the two share cannot disagree.

**Check:** both `fhir.toml` files state the same selection.

```bash
grep -A2 '^\[generate.organisation_units\]' national/registry/fhir.toml national/guide/fhir.toml
```

Both must say the same `root` and `max_level`. The registry's decides which
organisation units exist; the guide's decides which organisation units its forms
may be assigned to. A guide table left empty reads the whole instance -
including the deactivated subtree - and its forms then reference organisation
units the registry never published, which the IG publisher cannot resolve.
`--org-unit-root` and `--org-unit-max-level` write both at once, which is why
they are worth passing here rather than editing afterwards.

## 3. Choose the forms

The guide's `fhir.toml` has one table per kind of form. Name the ones you want
by UID:

```toml
[generate.data_sets]
include_ids = ["BfMAe6Itzgt", "QX4ZTUbOt3a"]

[generate.tracker_programs]
include_ids = ["IpHINAT79UW"]

[generate.event_programs]
enabled = false
```

**An absent table, or one without `include_ids`, means every member of its
kind.** A guide naming data sets and tracker programs but leaving
`[generate.event_programs]` empty publishes every event program on the
instance - dozens, on a national one. Write `enabled = false` for a kind you do
not want at all.

**Check:** every UID you listed is on this instance.

```bash
d2w -p national metadata list dataSets --filter 'id:in:[BfMAe6Itzgt,QX4ZTUbOt3a]' --fields id,name
d2w -p national metadata list programs --filter 'id:in:[IpHINAT79UW]' --fields id,name,programType
```

A UID copied from another instance - a local copy, a training server - selects
nothing here. Generate names each one in its notes and the guide builds without
that form, so compare the counts now rather than after a build.

## 4. Validate the instance

```bash
cd national/registry && d2w fhir validate
cd ../guide && d2w fhir validate
```

Each writes `reports/fhir-validate-report.md` (and `.csv`, `.pdf`) and ends
with a count per severity. Read the **errors** first: an error is something the
build would die on, and generate refuses the same objects.

The scaffold sets `hostile_names = "substitute"` in `[generate]`, and most of
what a real instance carries is then informational: a name or a code with `<`
is published in rewritten wording (`Female, <15y` as `Female, under 15y`, a code
`ENTO - IRS < 6 Months` as `ENTO---IRS-under-6-Months`), a code with spaces is
hyphenated, and each rewrite states the DHIS2 spelling beside it. DHIS2 is never
written to. [Validate an instance](201-validate.md) explains every category.

Two findings are worth sending to whoever looks after the metadata, because
they are fixed in DHIS2 and nowhere else:

- `invisible-character` - a zero-width space or similar pasted into a name or a
  code. The report prints it as `​`. Retype the value in DHIS2; editing
  around a character nobody can see does not remove it.
- `missing-code` on organisation units - the unit publishes under its UID only.

## 5. Generate

```bash
cd national/registry && d2w fhir generate
cd ../guide && d2w fhir generate
```

The registry writes one `Organization` and one `Location` per organisation
unit as pre-built JSON. The guide writes the forms, the code lists and the
pages, and references every organisation unit by its URL in the registry.

**Check:** read the notes each run points at, `reports/fhir-generate-notes.md`.
The ones to act on are the selection notes - a UID that matched nothing, a form
no published organisation unit may report - and the counts at the top of the
run, which should match what you meant to publish.

## 6. Check what the build will meet

```bash
cd national/guide && d2w fhir check-artifacts
```

This reads the files a build would publish, offline, and names everything the
IG publisher aborts on - before an hour of build time is spent finding it. In
the guide it also resolves every organisation unit reference against the
registry checkout beside it.

**Check:** `build-aborting 0`. The finding to recognise:

```text
the guide references an organisation unit the registry package it depends on does not publish
```

means the two selections from step 2 have come apart. Give the guide the
registry's `root` and `max_level`, then generate the guide again.

## 7. Build

The registry is built first: the guide's build installs the registry's
`package.tgz` into the publisher's package cache and resolves its references
against it.

```bash
cd national/registry && make build
cd ../guide && make build
```

`make build` runs the IG publisher in Docker; `make build` in the `national/`
directory runs the two in this order for you. Each build states the heap it
chose and, as it finishes, the memory it needed:

```text
publisher heap 8g, docker memory 24.0 GB
...
peak memory in use 13.5 GB - the heap, the JVM around it and Jekyll, sampled every 5 seconds
peak container memory 20.6 GB, counting file cache the kernel reclaims when memory runs short
```

**Leave `JAVA_HEAP` alone.** The derived heap - the memory Docker reports less
6 GB, capped at 8g - is enough for a national registry: on one of about twelve
thousand organisation units the publisher never used more than 7 GB of it,
with or without the boundaries. A larger heap does not help. The JVM grows into
whatever ceiling it is given, and Jekyll needs about 4 GB beside it at the end,
so a larger heap is how a build gets killed.

If a build does fail on memory, the two failures look different and need
opposite fixes:

- `BUILD KILLED - out of memory (exit 137)`: the machine ran out. Stop other
  containers, or give Docker more memory; lower `JAVA_HEAP` if you raised it.
- `java.lang.OutOfMemoryError` with a stack trace: the heap is too small for
  this guide. Raise it - `make build JAVA_HEAP=12g` - with Docker sized for the
  new ceiling plus 6 GB.

The site of each is in its `ig/output/`: open `index.html`, and `qa.html` for
the publisher's own report.

## 8. Look at it

```bash
cd national/guide && d2w fhir serve . --ui
```

serves the guide's forms with the capture UI, and the organisation units out of
the registry package. `d2w fhir serve --live` reads the instance instead of the
built guide, which needs no build at all - useful for trying a form before the
build finishes.

## Keeping it current

The registry and the guide change on different cadences - organisation units
monthly, forms yearly - which is the point of splitting them. Regenerate and
rebuild the one that changed; bump its `version` in `fhir.toml` when you
republish it, and the guide's `[generate.organisation_units.registry] version`
with it.

To move both projects to a new release of the tooling:

```bash
cd national && make update
```

That moves each project's `d2w` pin, syncs it, and refreshes the scaffold files -
the Makefiles and `fhir.example.toml` - without touching either `fhir.toml`.

## When a step fails

| What you see | What it means | What to do |
| --- | --- | --- |
| `check-artifacts`: `the guide references an organisation unit the registry package it depends on does not publish` | The guide's `[generate.organisation_units]` is wider than the registry's, usually an empty table. | Copy the registry's `root` and `max_level` into the guide, then `d2w fhir generate` in the guide. |
| Generate notes: a UID that selected nothing | The UID is not on this instance - often copied from another one. | Correct it in the `include_ids` table, or drop it. |
| Far more forms than you listed | A form table without `include_ids` means every form of that kind. | Add `include_ids`, or `enabled = false`. |
| `error: ... has code '...', which carries '<'` from generate | `hostile_names` is `refuse` or unset. | Set `hostile_names = "substitute"` in `[generate]`, or change the code in DHIS2. |
| `qa.html` reports `XHTML_URL_INVALID` on a `tel:` link | A phone number with an invisible character, published by a release before 1.28.0. | `make update`, then generate again. Retype the number in DHIS2 as well. |
| `BUILD KILLED - out of memory (exit 137)` | The container ran out of memory. | Stop other containers; leave `JAVA_HEAP` unset or at `8g`; give Docker more memory. |
| `OutOfMemoryError` with a Java stack trace | The heap is too small for this guide. | `make build JAVA_HEAP=12g`, with Docker sized for it. |

[Troubleshooting](201-troubleshooting.md) has the full list, by command.
