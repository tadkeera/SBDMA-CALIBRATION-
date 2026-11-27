/**
 * Who may open a unit's shelf of tests, and who may only read it.
 *
 * Release 2.4.0 shipped a guard in `Shell` that sent every principal who is not an
 * operator (ANALYST, SUPERVISOR) back to the dashboard as soon as it left `/lab/units`.
 * The tile that exists to be clicked therefore threw QA and the administrators out of the
 * laboratory: the twenty tests were rendered for a moment and then replaced by the
 * dashboard. The rule these two functions express is the one the laboratory actually
 * needs, so it is testable without a browser:
 *
 *   * reading the register — the shelf, a unit, its twenty tiles — is open to any role
 *     that may view instruments and to the office that reviews results;
 *   * *working* on a unit (readings, Run Calibration, Save) stays with the bench, and the
 *     API refuses it for everyone else whatever the browser does;
 *   * registering a unit stays an administrative act.
 */

export interface ShelfPrincipal {
  /** CALIBRATION.RUN — the bench (ANALYST, SUPERVISOR) and the super administrator. */
  canRun: boolean;
  /** INSTRUMENTS.VIEW — the register itself. */
  canViewInstruments: boolean;
  /** INSTRUMENTS.CREATE — registering a unit. */
  canCreateInstrument: boolean;
  /** CALIBRATION.REVIEW — QA and the administrator offices. */
  canReview: boolean;
}

/** `/lab/units`: the shelf of units. */
export function mayOpenShelf(principal: ShelfPrincipal): boolean {
  return principal.canViewInstruments;
}

/**
 * `/lab/{unit}` and `/lab/{unit}/{test}`: the twenty tiles and a test's own page.
 *
 * The same answer as the shelf, on purpose. These three screens are one register — the
 * units, their tests, and what the protocol asks of a test — and a role that may read the
 * first may read the rest. Splitting the answer is what produced the defect: the shelf was
 * open to ``instruments.view`` while the unit below it was open only to operators, so the
 * tile a reader was invited to click threw it back to the dashboard.
 */
export function mayOpenUnit(principal: ShelfPrincipal): boolean {
  return principal.canViewInstruments;
}

/** Whether the readings panel and Run Calibration are live, or read-only. */
export function mayWorkOnUnit(principal: ShelfPrincipal): boolean {
  return principal.canRun;
}
