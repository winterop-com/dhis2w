import { useEffect, useState } from 'react'

import { readResource } from '@/lib/api'
import type { ResourceList } from '@/lib/fhir'
import { assignedUnitIds } from '@/lib/orgunits'

/**
 * The organisation units each attribute-option-combination restriction List holds.
 *
 * WHY THE PICKER NEEDS THEM. DHIS2 scopes a category option to organisation units, a combination is
 * usable only where every option behind it is, and the vocabulary states that as one `List`
 * reference per restricted option on the concept. Deciding whether a combination may be captured at
 * the chosen unit is therefore a read of those Lists - the same read
 * `dhis2w_fhir_serve.capture.index._combo_restrictions` does before it grades a posted capture.
 *
 * WHY THEY ARE READ ONCE AND DEDUPLICATED. One category option restricts many combinations, so
 * sixty-four concepts name far fewer Lists than sixty-four. The distinct ids are read together, and
 * the module-level cache keeps them for the life of the tab for the same reason the registry and the
 * expansions are cached: the store behind this server is loaded at startup and never written.
 *
 * WHY A MISSING LIST IS NOT A FAILURE. A List this server does not publish narrows nothing, exactly
 * as an unresolvable assignment does not narrow a form - so a 404 leaves the id out of the map and
 * the combination stays on offer, rather than disabling a choice the server would have accepted.
 */

/** Which organisation units each restriction List holds, and whether the reads have landed. */
export interface ComboRestrictionMembers {
    /** The units each published List holds, keyed by List id. An id absent from it narrows nothing. */
    listMembers: ReadonlyMap<string, ReadonlySet<string>>
    loading: boolean
}

/** Nothing read yet - what the picker grades against before the first byte lands. */
const NOTHING_READ: ComboRestrictionMembers = { listMembers: new Map(), loading: false }

/** Every restriction List this session has read, keyed by the id a concept names it under. */
const lists = new Map<string, Promise<ReadonlySet<string> | null>>()

/** What one set of reads answered, stamped with the Lists it was read for. */
interface AnsweredMembers {
    key: string
    listMembers: ReadonlyMap<string, ReadonlySet<string>>
}

/**
 * The members of every restriction List a form's combinations name, read once per session.
 *
 * The dependency is the joined ids rather than the array: a fresh array of the same ids arrives on
 * every render of a page that re-read its vocabulary, and keying on its identity would read the
 * same Lists on every paint.
 */
export function useComboRestrictionMembers(listIds: string[]): ComboRestrictionMembers {
    const key = Array.from(new Set(listIds)).toSorted().join(' ')
    const [answered, setAnswered] = useState<AnsweredMembers | null>(null)

    useEffect(() => {
        if (key === '') return
        let cancelled = false
        readMembers(key.split(' ')).then((read) => {
            if (cancelled) return
            setAnswered({ key, listMembers: read })
        })
        return () => {
            cancelled = true
        }
    }, [key])

    if (key === '') return NOTHING_READ
    if (answered === null || answered.key !== key) return { listMembers: new Map(), loading: true }
    return { listMembers: answered.listMembers, loading: false }
}

/** Read every named List, leaving out the ones this server does not publish. */
async function readMembers(listIds: string[]): Promise<ReadonlyMap<string, ReadonlySet<string>>> {
    const read = await Promise.all(listIds.map(async (listId) => [listId, await readList(listId)] as const))
    return new Map(read.filter((entry): entry is [string, ReadonlySet<string>] => entry[1] !== null))
}

/** One restriction List's members, or null when this server publishes no such List. */
async function readList(listId: string): Promise<ReadonlySet<string> | null> {
    const known = lists.get(listId)
    if (known !== undefined) return known
    const started = readResource<ResourceList>('List', listId)
        .then((list) => new Set(assignedUnitIds(list)) as ReadonlySet<string>)
        .catch(() => null)
    lists.set(listId, started)
    return started
}
