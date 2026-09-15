import { describe, expect, it } from 'vitest'

import { QUARANTINED_LABEL, QUARANTINED_SUBTITLE, subtitleFor } from '@/pages/Overview'
import { RESPONSE_LIFECYCLES, type SpoolCounts } from '@/lib/spool'

/**
 * The line under each count on the receipts tiles, read as prose.
 *
 * Five tiles sit on one row and each carries a label and a line under it. The line says where the
 * receipts behind that count are - a fact, in one register - and a capitalised sentence among four
 * lower-case fragments is the same fact wearing two costumes.
 */
const NO_COUNTS: SpoolCounts = { received: 0, forwarded: 0, rejected: 0, withdrawn: 0, malformed: 0 }

describe('the line under a receipts tile', () => {
    const lines = [
        ...RESPONSE_LIFECYCLES.map((lifecycle) => subtitleFor(lifecycle, NO_COUNTS, null)),
        QUARANTINED_SUBTITLE,
    ]

    it('is a lower-case fragment on every tile, the fifth included', () => {
        expect(lines).toHaveLength(5)
        for (const line of lines) {
            expect(line[0]).toBe(line[0]?.toLowerCase())
            expect(line.endsWith('.')).toBe(false)
        }
    })

    it('says where the receipts are rather than restating the label above it', () => {
        expect(QUARANTINED_SUBTITLE.toLowerCase()).not.toContain(QUARANTINED_LABEL.toLowerCase())
        expect(QUARANTINED_SUBTITLE).toBe('set aside, never read as a response')
    })
})
