/**
 * Executed under Node by backend/tests/test_protocol_parity.py.
 * Reads { policySource, inputs } from argv[2] and prints the TypeScript engine's
 * verdicts as JSON so the Python engine can be compared against it.
 */
import { readFileSync } from 'node:fs';
import { runCalibration } from '../../src/core/engine/runEngine';
import type { LimitSource } from '../../src/core/types';

const payload = JSON.parse(readFileSync(process.argv[2], 'utf8')) as {
  policySource: LimitSource;
  inputs: Record<string, Record<string, unknown>>;
};

const run = runCalibration(payload.inputs, { policySource: payload.policySource });

console.log(
  JSON.stringify({
    overall: run.overall,
    results: run.results.map((r) => ({
      testCode: r.testCode,
      status: r.status,
      metrics: r.metricEvaluations.map((m) => ({
        metricKey: m.metricKey,
        status: m.status,
      })),
    })),
  }),
);
