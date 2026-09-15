import { describe, expect, it } from 'vitest'

import {
    attributeOptionComboRestrictionOf,
    gradeAttributeOptionCombo,
    periodSpan,
    UNRESTRICTED_COMBO,
    type AttributeOptionComboContext,
} from '@/lib/attributecombos'
import type { CodeSystemConceptProperty } from '@/lib/fhir'

/** A submission with nothing chosen yet, which is what every form opens on. */
const NOTHING_CHOSEN: AttributeOptionComboContext = {
    span: null,
    unitId: null,
    unitName: null,
    listMembers: new Map(),
}

describe('what a combination concept says about where and when it may be captured', () => {
    it('reads the restriction Lists it names and the window its options are open for', () => {
        const properties: CodeSystemConceptProperty[] = [
            { code: 'dhis2-code', valueString: 'COC_1452093' },
            { code: 'dhis2-organisation-units', valueString: 'List/d2-aoc-O4VaNks6tta-OUUdG3sdOqb-org-units' },
            { code: 'dhis2-valid-from', valueDateTime: '2012-01-01' },
            { code: 'dhis2-valid-to', valueDateTime: '2016-10-01' },
        ]

        expect(attributeOptionComboRestrictionOf(properties)).toEqual({
            listIds: ['d2-aoc-O4VaNks6tta-OUUdG3sdOqb-org-units'],
            validFrom: '2012-01-01',
            validTo: '2016-10-01',
        })
    })

    it('reads a window stated as a full R4 dateTime as the calendar day it falls on', () => {
        // DHIS2 scopes a category option by calendar day, so the clock a `dateTime` may carry says
        // nothing more - exactly what `_concept_date` reads on the server.
        const restriction = attributeOptionComboRestrictionOf([
            { code: 'dhis2-valid-to', valueDateTime: '2016-10-01T00:00:00.000Z' },
        ])

        expect(restriction.validTo).toBe('2016-10-01')
    })

    it('states nothing for a concept carrying neither axis, which is every unrestricted combination', () => {
        expect(attributeOptionComboRestrictionOf([{ code: 'dhis2-code', valueString: 'COC_1452090' }])).toEqual(
            UNRESTRICTED_COMBO,
        )
    })

    it('passes over a restriction property that references something other than a List', () => {
        const restriction = attributeOptionComboRestrictionOf([
            { code: 'dhis2-organisation-units', valueString: 'Location/O6uvpzGd5pu' },
        ])

        expect(restriction.listIds).toEqual([])
    })
})

describe('the days one DHIS2 period covers', () => {
    it('spans the seven period types whose arithmetic is the calendar own', () => {
        expect(periodSpan('20161015', 'Daily')).toEqual({ start: '2016-10-15', end: '2016-10-15' })
        expect(periodSpan('2026W30', 'Weekly')).toEqual({ start: '2026-07-20', end: '2026-07-26' })
        expect(periodSpan('201610', 'Monthly')).toEqual({ start: '2016-10-01', end: '2016-10-31' })
        expect(periodSpan('201609B', 'BiMonthly')).toEqual({ start: '2016-09-01', end: '2016-10-31' })
        expect(periodSpan('2016Q4', 'Quarterly')).toEqual({ start: '2016-10-01', end: '2016-12-31' })
        expect(periodSpan('2016S2', 'SixMonthly')).toEqual({ start: '2016-07-01', end: '2016-12-31' })
        expect(periodSpan('2016', 'Yearly')).toEqual({ start: '2016-01-01', end: '2016-12-31' })
    })

    it('reads February off the calendar rather than off a table of month lengths', () => {
        expect(periodSpan('201602', 'Monthly')?.end).toBe('2016-02-29')
        expect(periodSpan('201702', 'Monthly')?.end).toBe('2017-02-28')
    })

    it('spans nothing for a type whose numbering states an offset this UI does not hold', () => {
        // A financial year and an offset week number themselves from something the browser has no
        // way to know, and a guessed span would mark a combination closed that DHIS2 takes happily.
        expect(periodSpan('2026April', 'FinancialApril')).toBeNull()
        expect(periodSpan('2026WedW30', 'WeeklyWednesday')).toBeNull()
        expect(periodSpan('202610', null)).toBeNull()
    })

    it('spans nothing for an identifier that is not of the type it is read as', () => {
        expect(periodSpan('july', 'Monthly')).toBeNull()
        expect(periodSpan('2016Q5', 'Quarterly')).toBeNull()
    })
})

describe('whether this DHIS2 instance takes a capture under one combination', () => {
    const closedInOctober = { listIds: [], validFrom: null, validTo: '2016-10-01' }
    const restrictedToOneUnit = { listIds: ['d2-aoc-restricted-org-units'], validFrom: null, validTo: null }
    const oneUnitHeld = new Map([['d2-aoc-restricted-org-units', new Set(['O6uvpzGd5pu'])]])

    it('takes a capture under a combination nothing rules out', () => {
        expect(gradeAttributeOptionCombo(UNRESTRICTED_COMBO, NOTHING_CHOSEN)).toEqual({ usable: true, reason: null })
    })

    it('closes a combination whose window ends before the chosen period does', () => {
        // DHIS2's own rule: the whole period has to sit inside the window, so October 2016 is already
        // outside a window that closes on the first of it - `E8032 Untimely data entry`.
        const grade = gradeAttributeOptionCombo(closedInOctober, {
            ...NOTHING_CHOSEN,
            span: periodSpan('201610', 'Monthly'),
        })

        expect(grade).toEqual({ usable: false, reason: 'Closed on 2016-10-01' })
    })

    it('leaves the same combination on offer for a period its window covers entirely', () => {
        const grade = gradeAttributeOptionCombo(closedInOctober, {
            ...NOTHING_CHOSEN,
            span: periodSpan('201609', 'Monthly'),
        })

        expect(grade.usable).toBe(true)
    })

    it('says when a combination is not open yet rather than that it is closed', () => {
        const grade = gradeAttributeOptionCombo(
            { listIds: [], validFrom: '2017-01-01', validTo: null },
            { ...NOTHING_CHOSEN, span: periodSpan('201610', 'Monthly') },
        )

        expect(grade).toEqual({ usable: false, reason: 'Not open until 2017-01-01' })
    })

    it('grades no window at all when the chosen period spans nothing this UI can read', () => {
        expect(gradeAttributeOptionCombo(closedInOctober, { ...NOTHING_CHOSEN, span: null }).usable).toBe(true)
    })

    it('names the organisation unit a combination is restricted away from', () => {
        const grade = gradeAttributeOptionCombo(restrictedToOneUnit, {
            span: null,
            unitId: 'DiszpKrYNg8',
            unitName: 'Ngelehun CHC',
            listMembers: oneUnitHeld,
        })

        expect(grade).toEqual({ usable: false, reason: 'Not capturable at Ngelehun CHC' })
    })

    it('leaves it on offer at an organisation unit its restriction List holds', () => {
        const grade = gradeAttributeOptionCombo(restrictedToOneUnit, {
            span: null,
            unitId: 'O6uvpzGd5pu',
            unitName: 'Badjia',
            listMembers: oneUnitHeld,
        })

        expect(grade.usable).toBe(true)
    })

    it('narrows nothing on a restriction List this server does not publish', () => {
        // An artifact this project did not publish states nothing, exactly as an unresolvable
        // assignment does not narrow a form. The picker offers what the server would accept.
        const grade = gradeAttributeOptionCombo(restrictedToOneUnit, {
            span: null,
            unitId: 'DiszpKrYNg8',
            unitName: 'Ngelehun CHC',
            listMembers: new Map(),
        })

        expect(grade.usable).toBe(true)
    })

    it('grades the date axis before the organisation-unit axis, so one refusal is one fact', () => {
        const grade = gradeAttributeOptionCombo(
            { listIds: ['d2-aoc-restricted-org-units'], validFrom: null, validTo: '2016-10-01' },
            {
                span: periodSpan('201610', 'Monthly'),
                unitId: 'DiszpKrYNg8',
                unitName: 'Ngelehun CHC',
                listMembers: oneUnitHeld,
            },
        )

        expect(grade.reason).toBe('Closed on 2016-10-01')
    })
})
