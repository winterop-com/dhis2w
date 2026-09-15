/**
 * Where and when one attribute option combination may be captured, read off the vocabulary itself.
 *
 * WHY A CLIENT GRADES THIS AT ALL. DHIS2 scopes a category option two ways - to a set of
 * organisation units, and to a calendar window - and a combination is usable only where every
 * option behind it is on both. A capture outside the unit axis is refused `E8025`, one outside the
 * date axis `E8032`, and the vocabulary the picker is already reading carries both facts: the
 * concept names one restriction `List` per restricted option on `dhis2-organisation-units`, and
 * states the narrowest window its options are open for on `dhis2-valid-from` / `dhis2-valid-to`.
 * So a control that offered all sixty-four would be offering sixteen the server beside it refuses
 * to draw for. The grading here is the same grading the facade does (`_combo_restrictions` and
 * `CaptureComboRestriction` in `dhis2w_fhir_serve.capture.index`), read from the same bytes.
 *
 * WHY A MISSING FACT NARROWS NOTHING. Absence on either axis is the vocabulary saying the option was
 * always open, or is available everywhere - which is exactly how the facade reads it. A restriction
 * `List` this server does not publish narrows nothing either, for the reason an unresolvable
 * assignment does not narrow a form: an artifact this project did not publish states nothing.
 *
 * WHY THE DATE ARITHMETIC IS HERE AND THE REST IS NOT. `periodSpan` turns a DHIS2 period identifier
 * into the days it covers, and it does so for exactly the period types `PERIOD_FAMILIES` already
 * counts back through - the ones whose arithmetic is the calendar's own and nothing is guessed. A
 * type outside that set spans nothing here, and every combination is offered unmarked rather than
 * marked from a guess: the server grades it either way, and says which window it fell outside.
 */

import type { CodeSystemConceptProperty } from '@/lib/fhir'

/** The concept property naming one restriction List, repeated once per restricted category option. */
export const ATTRIBUTE_OPTION_RESTRICTION_PROPERTY = 'dhis2-organisation-units'

/** The concept properties stating the calendar window every category option of the combination is open for. */
export const ATTRIBUTE_OPTION_VALID_FROM_PROPERTY = 'dhis2-valid-from'
export const ATTRIBUTE_OPTION_VALID_TO_PROPERTY = 'dhis2-valid-to'

/** The resource type a restriction is published as, and the prefix of the reference a property carries. */
const RESTRICTION_REFERENCE_PREFIX = 'List/'

/** How many leading characters of an R4 `dateTime` spell the calendar day it falls on. */
const ISO_DATE_LENGTH = 10

/** Where and when one attribute option combination may be captured, as its own concept states both axes. */
export interface AttributeOptionComboRestriction {
    /** The ids of the restriction Lists the concept names, in the order it names them. */
    listIds: string[]
    /** The first day the combination is open for, or null where every option behind it was always open. */
    validFrom: string | null
    /** The last day the combination is open for, or null where no option behind it is ever closed. */
    validTo: string | null
}

/** A combination whose concept states neither axis - open always, capturable everywhere. */
export const UNRESTRICTED_COMBO: AttributeOptionComboRestriction = { listIds: [], validFrom: null, validTo: null }

/** What one concept's properties say about where and when the combination may be captured. */
export function attributeOptionComboRestrictionOf(
    properties: CodeSystemConceptProperty[],
): AttributeOptionComboRestriction {
    return {
        listIds: properties
            .filter((property) => property.code === ATTRIBUTE_OPTION_RESTRICTION_PROPERTY)
            .map((property) => property.valueString)
            .filter(
                (reference): reference is string =>
                    reference !== undefined && reference.startsWith(RESTRICTION_REFERENCE_PREFIX),
            )
            .map((reference) => reference.slice(RESTRICTION_REFERENCE_PREFIX.length)),
        validFrom: conceptDay(properties, ATTRIBUTE_OPTION_VALID_FROM_PROPERTY),
        validTo: conceptDay(properties, ATTRIBUTE_OPTION_VALID_TO_PROPERTY),
    }
}

/**
 * One calendar day a concept property states, or null where it states none this can read.
 *
 * An R4 `dateTime` admits more than a day - a time, an offset - and DHIS2 scopes a category option
 * by calendar day, so the day is what is read and anything beyond it is passed over. Exactly what
 * `_concept_date` does on the server, so a window read here is the window read there.
 */
function conceptDay(properties: CodeSystemConceptProperty[], code: string): string | null {
    const stated = properties.find((property) => property.code === code)?.valueDateTime
    if (stated === undefined) return null
    const calendarDay = stated.slice(0, ISO_DATE_LENGTH)
    return /^\d{4}-\d{2}-\d{2}$/.test(calendarDay) ? calendarDay : null
}

/** The days one DHIS2 reporting period covers, both ends inclusive, as calendar days. */
export interface PeriodSpan {
    /** The first day of the period, as `2016-10-01`. */
    start: string
    /** The last day of the period, as `2016-10-31`. */
    end: string
}

/** One day as DHIS2 and R4 both spell it. */
function day(year: number, monthIndex: number, dayOfMonth: number): string {
    const month = String(monthIndex + 1).padStart(2, '0')
    return `${String(year).padStart(4, '0')}-${month}-${String(dayOfMonth).padStart(2, '0')}`
}

/** The last day of one month, read off the calendar rather than off a table of lengths. */
function lastDayOfMonth(year: number, monthIndex: number): number {
    return new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate()
}

/** The whole of one month, or of a run of months beginning at one. */
function monthsSpan(year: number, monthIndex: number, months: number): PeriodSpan {
    const lastMonth = new Date(Date.UTC(year, monthIndex + months - 1, 1))
    const lastYear = lastMonth.getUTCFullYear()
    const lastMonthIndex = lastMonth.getUTCMonth()
    return {
        start: day(year, monthIndex, 1),
        end: day(lastYear, lastMonthIndex, lastDayOfMonth(lastYear, lastMonthIndex)),
    }
}

/** The Monday one ISO-8601 week opens on - the same week numbering DHIS2 spells `2026W30`. */
function mondayOfIsoWeek(weekYear: number, week: number): Date {
    const fourthOfJanuary = new Date(Date.UTC(weekYear, 0, 4))
    const firstMonday = new Date(fourthOfJanuary.getTime())
    firstMonday.setUTCDate(fourthOfJanuary.getUTCDate() - ((fourthOfJanuary.getUTCDay() + 6) % 7))
    return new Date(firstMonday.getTime() + (week - 1) * 7 * 86_400_000)
}

/** One instant as the calendar day it falls on, in UTC. */
function dayOf(instant: Date): string {
    return day(instant.getUTCFullYear(), instant.getUTCMonth(), instant.getUTCDate())
}

/**
 * The days one DHIS2 period identifier covers, or null for a type whose arithmetic is not the calendar's.
 *
 * SEVEN OF THE NINETEEN, and the same seven `PERIOD_FAMILIES` offers, for the same reason: the
 * offset weeks (`2026WedW30`), the two-week periods and the financial years (`2026April`) number
 * themselves from an offset this UI does not hold, and a span guessed for one of them would mark a
 * combination closed that DHIS2 is perfectly happy to take. Null is this saying so.
 */
export function periodSpan(iso: string, periodType: string | null): PeriodSpan | null {
    const identifier = iso.trim()
    if (periodType === 'Daily' && /^\d{8}$/.test(identifier)) {
        return { start: isoDay(identifier), end: isoDay(identifier) }
    }
    if (periodType === 'Weekly') {
        const week = /^(\d{4})W(\d{1,2})$/.exec(identifier)
        if (week === null) return null
        const monday = mondayOfIsoWeek(Number(week[1]), Number(week[2]))
        return { start: dayOf(monday), end: dayOf(new Date(monday.getTime() + 6 * 86_400_000)) }
    }
    if (periodType === 'Monthly' && /^\d{6}$/.test(identifier)) {
        return monthsSpan(Number(identifier.slice(0, 4)), Number(identifier.slice(4, 6)) - 1, 1)
    }
    if (periodType === 'BiMonthly' && /^\d{6}B$/.test(identifier)) {
        return monthsSpan(Number(identifier.slice(0, 4)), Number(identifier.slice(4, 6)) - 1, 2)
    }
    if (periodType === 'Quarterly') {
        const quarter = /^(\d{4})Q([1-4])$/.exec(identifier)
        return quarter === null ? null : monthsSpan(Number(quarter[1]), (Number(quarter[2]) - 1) * 3, 3)
    }
    if (periodType === 'SixMonthly') {
        const half = /^(\d{4})S([12])$/.exec(identifier)
        return half === null ? null : monthsSpan(Number(half[1]), (Number(half[2]) - 1) * 6, 6)
    }
    if (periodType === 'Yearly' && /^\d{4}$/.test(identifier)) {
        return monthsSpan(Number(identifier), 0, 12)
    }
    return null
}

/** `20161015` as `2016-10-15`, which is the only reshaping a daily identifier needs. */
function isoDay(identifier: string): string {
    return `${identifier.slice(0, 4)}-${identifier.slice(4, 6)}-${identifier.slice(6, 8)}`
}

/** Whether this DHIS2 instance takes a capture keyed to one combination, and the fact when it does not. */
export interface AttributeOptionComboGrade {
    /** True when nothing the vocabulary states rules the combination out for the chosen period and unit. */
    usable: boolean
    /** The short fact that rules it out, or null when nothing does. */
    reason: string | null
}

/** A combination nothing rules out. */
export const COMBO_USABLE: AttributeOptionComboGrade = { usable: true, reason: null }

/** What one grading is asked about: the combination, and the submission it would be filed under. */
export interface AttributeOptionComboContext {
    /** The days the chosen period covers, or null where none is chosen or its type spans nothing here. */
    span: PeriodSpan | null
    /** The id of the chosen organisation unit, or null where nobody has chosen one yet. */
    unitId: string | null
    /** What that organisation unit is called, so a refusal names a place rather than an id. */
    unitName: string | null
    /**
     * The organisation units each published restriction List holds, keyed by List id.
     *
     * A List missing from the map is one this server does not publish, and it narrows nothing - the
     * facade reads an unpublished restriction the same way, so the picker offers what the server
     * would accept rather than a subset of it.
     */
    listMembers: ReadonlyMap<string, ReadonlySet<string>>
}

/**
 * Whether this DHIS2 instance takes a capture keyed to one combination, in one short sentence.
 *
 * THE DATE AXIS IS GRADED FIRST because it is a fact about the combination and the period alone: it
 * holds at every organisation unit, and a reader who changes the unit will meet it again. The unit
 * axis is graded second and names the place, so the two refusals never read as one.
 *
 * THE WHOLE PERIOD HAS TO SIT INSIDE THE WINDOW. DHIS2's own rule, which is why a period beginning
 * on the very day an option closes is already outside it: `CaptureComboRestriction.covers` grades a
 * served capture by exactly this test, and the generator keys an example by it.
 */
export function gradeAttributeOptionCombo(
    restriction: AttributeOptionComboRestriction,
    context: AttributeOptionComboContext,
): AttributeOptionComboGrade {
    const { span, unitId, unitName, listMembers } = context
    if (span !== null && restriction.validFrom !== null && span.start < restriction.validFrom) {
        return { usable: false, reason: `Not open until ${restriction.validFrom}` }
    }
    if (span !== null && restriction.validTo !== null && span.end > restriction.validTo) {
        return { usable: false, reason: `Closed on ${restriction.validTo}` }
    }
    if (unitId === null) return COMBO_USABLE
    const restrictedAway = restriction.listIds.some((listId) => {
        const members = listMembers.get(listId)
        return members !== undefined && !members.has(unitId)
    })
    return restrictedAway ? { usable: false, reason: `Not capturable at ${unitName ?? unitId}` } : COMBO_USABLE
}
