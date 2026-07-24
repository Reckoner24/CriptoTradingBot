## 2026-07-21T23:40:03Z
You are Worker 1 (E2E Testing Infrastructure Engineer).
Your working directory is c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_e2e_1.

Objective:
1. Design and create `TEST_INFRA.md` at project root (`c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\TEST_INFRA.md`). Document feature inventory, 4-tier methodology (Category-Partition, BVA, Pairwise, Real-World Workload), test runner command, and pass criteria.
2. Implement an automated E2E test suite in `tests/test_e2e_suite.py` (or `scripts/run_e2e_tests.py`) with 4 distinct tiers:
   - Tier 1 (Feature Coverage): >=5 tests per feature (grid entries, exit manager, risk governor, WFO, websocket, paper mode accounting).
   - Tier 2 (Boundary & Corner Cases): >=5 tests per feature (max margin caps, streak block, stale params rejection, intraday kill switch, zero volatility).
   - Tier 3 (Cross-Feature Pairwise): Test combinations (e.g., streak block + trailing stop retrace, dynamic risk governor + daily kill switch).
   - Tier 4 (Real-World Application Scenarios): Validate that `proyeccion_20d.py`, `parity_check_24h.py`, and `pytest tests/` execute and return successful pass status.
3. Run the full unit and E2E test suite using `run_command` (`python -m pytest tests/ -v`).
4. Upon 100% pass status, create `TEST_READY.md` at project root (`c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\TEST_READY.md`) summarizing test counts, coverage per tier, and runner invocation command.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

5. Create `handoff.md` in your working directory detailing test suite structure, command output, and verification proof.
6. Send a completion message to the orchestrator with the handoff summary and file paths.
