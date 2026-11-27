/**
 * The laboratory's access rules, without a browser.
 *
 * These four cases are the regression this suite exists for: release 2.4.0 sent QA and
 * both administrative offices back to the dashboard as soon as they opened a unit, so the
 * twenty tests could not be read by the office that reviews and approves them.
 */

import { describe, expect, it } from 'vitest';

import { mayOpenShelf, mayOpenUnit, mayWorkOnUnit } from '../src/core/labAccess';

/** Permissions each role holds, as `backend/app/core/rbac.py` defines them. */
const ROLE = {
  analyst: { canRun: true, canViewInstruments: true, canCreateInstrument: false, canReview: false },
  supervisor: { canRun: true, canViewInstruments: true, canCreateInstrument: false, canReview: true },
  qa: { canRun: false, canViewInstruments: true, canCreateInstrument: false, canReview: true },
  systemAdmin: { canRun: false, canViewInstruments: true, canCreateInstrument: true, canReview: true },
  superAdmin: { canRun: true, canViewInstruments: true, canCreateInstrument: true, canReview: true },
  viewer: { canRun: false, canViewInstruments: true, canCreateInstrument: false, canReview: false },
} as const;

describe('the laboratory shelf', () => {
  it('is open to every role that may view instruments', () => {
    for (const [name, principal] of Object.entries(ROLE)) {
      expect(mayOpenShelf(principal), `${name} may open /lab/units`).toBe(true);
    }
  });

  it('is closed to a role with no instruments.view', () => {
    expect(
      mayOpenShelf({ canRun: false, canViewInstruments: false, canCreateInstrument: false, canReview: false }),
    ).toBe(false);
  });
});

describe('a unit and its twenty tiles', () => {
  it('opens for QA — the office that reviews the results the tiles lead to', () => {
    // the reported defect: this was false in 2.4.0 and the tile bounced to the dashboard
    expect(mayOpenUnit(ROLE.qa)).toBe(true);
  });

  it('opens for both administrative offices, which register units and read the register', () => {
    expect(mayOpenUnit(ROLE.systemAdmin)).toBe(true);
    expect(mayOpenUnit(ROLE.superAdmin)).toBe(true);
  });

  it('opens for the bench', () => {
    expect(mayOpenUnit(ROLE.analyst)).toBe(true);
    expect(mayOpenUnit(ROLE.supervisor)).toBe(true);
  });

  it('opens for a read-only viewer, because it is the same register as the shelf', () => {
    expect(mayOpenShelf(ROLE.viewer)).toBe(true);
    expect(mayOpenUnit(ROLE.viewer)).toBe(true);
  });

  it('is closed to a principal with no instruments.view at all', () => {
    expect(
      mayOpenUnit({ canRun: true, canViewInstruments: false, canCreateInstrument: false, canReview: false }),
    ).toBe(false);
  });
});

describe('entering readings', () => {
  it('stays with the bench, whatever a reader may open', () => {
    expect(mayWorkOnUnit(ROLE.analyst)).toBe(true);
    expect(mayWorkOnUnit(ROLE.supervisor)).toBe(true);
    expect(mayWorkOnUnit(ROLE.qa)).toBe(false);
    expect(mayWorkOnUnit(ROLE.systemAdmin)).toBe(false);
  });

  it('is not implied by being able to read the shelf', () => {
    // reading and measuring are two different questions, which is what 2.4.0 conflated
    expect(mayOpenUnit(ROLE.qa)).toBe(true);
    expect(mayWorkOnUnit(ROLE.qa)).toBe(false);
  });
});
