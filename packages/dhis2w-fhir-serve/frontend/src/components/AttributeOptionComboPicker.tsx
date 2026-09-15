import { Loader2 } from 'lucide-react'

import { Label } from '@/components/ui/label'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select'
import { useComboRestrictionMembers } from '@/hooks/use-combo-restrictions'
import { useValueSetOptions, type ValueSetOption } from '@/hooks/use-valueset-options'
import {
    attributeOptionComboRestrictionOf,
    gradeAttributeOptionCombo,
    periodSpan,
    UNRESTRICTED_COMBO,
    type AttributeOptionComboGrade,
} from '@/lib/attributecombos'
import { attributeOptionComboLabel, type Coding } from '@/lib/fhir'

/** The one control on a capture form whose id is fixed, so its label and its trigger can find each other. */
const CONTROL_ID = 'attribute-option-combo'

/** One combination on offer, beside whether this DHIS2 instance takes a capture under it. */
interface GradedOption {
    option: ValueSetOption
    grade: AttributeOptionComboGrade
}

/**
 * Which attribute option combo a whole submission is filed under.
 *
 * WHY THIS IS NOT A QUESTION. A DHIS2 data value is keyed by three things - the organisation unit,
 * the reporting period, and the attribute option combo - and a data set riding a non-default
 * category combo has to state the third or DHIS2 refuses the import with `E8023`. It is envelope
 * context in exactly the way the period and the unit are, which is why this sits above the form
 * rather than among its items: nothing in the response's `item` tree carries it, and rendering it
 * as a question would put a fact about the submission where the answers to the data elements are.
 *
 * WHY THE USER PICKS IT AND THE SERVER DOES NOT. The rest of the envelope comes from `$generate`
 * because deriving it would mean reimplementing DHIS2 period arithmetic in a browser. This one is
 * different in kind: which project a month of stock figures is reported under is not derivable from
 * anything at all - it is the thing the person filling the form knows and the server does not.
 *
 * WHY IT OPENS UNANSWERED. `$generate` draws a combo so its skeleton is postable, and this control
 * does not adopt that draw: a pre-selected combo is a claim about which project a month of figures
 * belongs to, made by a random draw on behalf of whoever did not look at it. DHIS2's own capture app
 * refuses to render the form until the combo is chosen; the same refusal in this app's idiom is a
 * control that is empty, marked required, and says what choosing it decides - and a Submit that
 * refuses with the reason stated.
 *
 * WHY THE CODE IS ON EVERY OPTION. Two attribute option combos of one category combo can read
 * almost the same ("Improve access to clean water", "Improve access to medicines"), and the uid is
 * what the receipt, the spool, the forwarder's refusals, and DHIS2 itself name them by - the same
 * argument the question labels make for their data element uids.
 *
 * WHY A CHOICE IS NOT THE SAME AS A DRAW. Once somebody picks here, "fill with test data" draws
 * FOR that combo rather than over it - the server is asked for a draft filed under it, and answers
 * with the reason where this DHIS2 instance takes no such capture. The line under the control says
 * so once a choice is made, because a control that looks identical before and after would be
 * claiming a random draw and a person's decision are the same fact.
 *
 * WHY THE UNUSABLE ONES ARE SHOWN RATHER THAN HIDDEN. DHIS2 opens a category option for a calendar
 * window and scopes it to organisation units, so a third of this vocabulary can be closed for the
 * period on screen. A control that silently dropped those would leave a person hunting for a
 * combination they know exists; one that offered them unmarked would let them pick a submission the
 * server beside it refuses to draw for. So every combination the form declares is listed, and the
 * ones DHIS2 takes no capture under for the chosen period and organisation unit say which of the
 * two rules they fall outside and take no choice.
 */
export function AttributeOptionComboPicker({
    canonical,
    selected,
    disabled = false,
    chosen = false,
    periodIso = null,
    periodType = null,
    unitId = null,
    unitName = null,
    onChange,
}: {
    /** The ValueSet the form declares its combos on - `d2-attribute-option-combos`, valueCanonical. */
    canonical: string
    selected: Coding | null
    /**
     * True on a form this DHIS2 instance accepts no capture for, whichever combo is named.
     *
     * The control still shows what the vocabulary holds - the choices are worth reading - but it
     * takes no choice, because every one of them names a submission the instance refuses. The page
     * says why above it, in the server's own words.
     */
    disabled?: boolean
    /** True once somebody has picked here, which is what makes the selection survive a refill. */
    chosen?: boolean
    /** The DHIS2 period identifier the submission reports for, which decides the date axis. */
    periodIso?: string | null
    /** The DHIS2 period type that identifier reads as, without which the days it covers are unknown. */
    periodType?: string | null
    /** The organisation unit the submission reports from, which decides the organisation-unit axis. */
    unitId?: string | null
    /** What that organisation unit is called, so a refusal names a place rather than an id. */
    unitName?: string | null
    onChange: (coding: Coding) => void
}) {
    const expansion = useValueSetOptions(canonical)
    const label = attributeOptionComboLabel(expansion.title)
    const restrictions = expansion.options.map((option) => attributeOptionComboRestrictionOf(option.properties))
    const { listMembers } = useComboRestrictionMembers(restrictions.flatMap((restriction) => restriction.listIds))
    const span = periodIso === null ? null : periodSpan(periodIso, periodType)
    const graded: GradedOption[] = expansion.options.map((option, index) => ({
        option,
        grade: gradeAttributeOptionCombo(restrictions[index] ?? UNRESTRICTED_COMBO, {
            span,
            unitId,
            unitName,
            listMembers,
        }),
    }))
    // A combination chosen before the period or the organisation unit moved under it. Saying nothing
    // would leave a person filing under a combination this DHIS2 instance no longer takes, on a
    // screen that shows the choice they made and none of what has happened to it since.
    const chosenGrade =
        selected?.code === undefined
            ? null
            : (graded.find((candidate) => candidate.option.coding.code === selected.code)?.grade ?? null)

    return (
        <div className="bg-card text-card-foreground grid gap-2 rounded-lg border p-4">
            <Label htmlFor={CONTROL_ID}>
                {label}
                <span className="text-destructive" aria-hidden>
                    *
                </span>
            </Label>
            <p className="text-muted-foreground text-sm">
                This data set is reported per attribute option combination, so every value below is
                filed under the one chosen here. It is context, not an answer - this DHIS2 instance
                keys the whole submission by it, beside the period and the organisation unit.
            </p>
            <div className="flex items-center gap-2">
                <Select
                    value={selected?.code ?? ''}
                    disabled={disabled || expansion.loading || expansion.options.length === 0}
                    onValueChange={(code) => {
                        const option = expansion.options.find((candidate) => candidate.coding.code === code)
                        if (option !== undefined) onChange(option.coding)
                    }}
                >
                    <SelectTrigger id={CONTROL_ID} className="w-full max-w-md">
                        <SelectValue placeholder={placeholder(expansion.loading, expansion.options.length)} />
                    </SelectTrigger>
                    <SelectContent>
                        {graded.map(({ option, grade }) => (
                            <SelectItem
                                key={option.coding.code ?? option.label}
                                value={option.coding.code ?? ''}
                                disabled={!grade.usable}
                            >
                                <span>{option.label}</span>
                                <span className="machine-identifier text-[10px]">
                                    {option.coding.code}
                                </span>
                                {grade.reason !== null && (
                                    <span className="text-muted-foreground text-xs">{grade.reason}</span>
                                )}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                {expansion.loading && (
                    <Loader2 className="text-muted-foreground size-4 shrink-0 animate-spin" aria-hidden />
                )}
            </div>

            {chosenGrade !== null && !chosenGrade.usable && (
                <p className="text-destructive text-xs">
                    This DHIS2 instance takes no capture under the attribute option combination
                    chosen here, for the period and organisation unit now on this form.{' '}
                    {chosenGrade.reason}. Choose another one.
                </p>
            )}
            {chosen && (
                <p className="text-muted-foreground text-xs">
                    Filling this form with test data keeps this attribute option combination and
                    draws the rest of the submission for it.
                </p>
            )}
            {expansion.error !== null && (
                <p className="text-destructive text-xs">
                    The attribute option combinations this form reports for could not be read:{' '}
                    {expansion.error}
                </p>
            )}
            {expansion.error === null && !expansion.loading && expansion.options.length === 0 && (
                <p className="text-muted-foreground text-xs">
                    This form names a vocabulary of attribute option combinations this server does
                    not publish, so there is nothing to choose from. A submission that names none is
                    refused on import by this DHIS2 instance.{' '}
                    <code className="font-mono">E8023</code>
                </p>
            )}
        </div>
    )
}

/** What the trigger says while there is nothing to pick from yet. */
function placeholder(loading: boolean, optionCount: number): string {
    if (loading) return 'Reading the attribute option combinations this form reports for'
    return optionCount === 0 ? 'No attribute option combinations published' : 'Not chosen'
}
