/**
 * Marks an English source string for extraction without translating it where it is declared
 * (module-level constants, page metadata). Render it later with `tr(text)`.
 * The completeness test collects every `N_('…')`, `t('…')`, `tw('…')`, `rich('…')` and `tn(n, {…})` literal.
 */
export const N_ = <T extends string>(text: T): T => text
