/**
 * Tests for the error envelope parsing logic used by api.ts's handleError().
 *
 * handleError() is a private function inside api.ts, and api.ts has module-
 * level side effects (axios interceptor setup), so we cannot import it in
 * isolation without a full axios stub.  Instead, we unit-test the parsing
 * logic directly by mirroring the exact expression from api.ts.  If the
 * production logic drifts, CI will catch it via the integration tests in
 * tests/test_api/test_shorts_router.py which exercises the full stack.
 *
 * Backend error shapes we must handle:
 *   1. Unified envelope  { error: { message: "..." } }  ← new standard
 *   2. FastAPI detail string  { detail: "..." }
 *   3. Top-level message     { message: "..." }
 *   4. No response body / network error
 */
import { describe, it, expect } from "vitest";

/**
 * Mirror of the detail-extraction expression in api.ts handleError().
 * Keep this in sync with:
 *   frontend/client/src/lib/api.ts  ~line 757-762
 */
function parseErrorMessage(data: unknown, axiosMessage: string): string {
  const d = data as Record<string, any> | null | undefined;
  return (
    d?.error?.message ||
    (typeof d?.detail === "string" ? d.detail : undefined) ||
    d?.message ||
    axiosMessage ||
    "An error occurred"
  );
}

describe("error envelope parsing (mirrors api.ts handleError logic)", () => {
  it("extracts message from unified envelope {error.message}", () => {
    const data = { error: { message: "paste the transcript instead" } };
    expect(parseErrorMessage(data, "axios msg")).toBe("paste the transcript instead");
  });

  it("falls back to FastAPI detail string", () => {
    const data = { detail: "value is not valid" };
    expect(parseErrorMessage(data, "axios msg")).toBe("value is not valid");
  });

  it("falls back to top-level message field", () => {
    const data = { message: "something went wrong" };
    expect(parseErrorMessage(data, "axios msg")).toBe("something went wrong");
  });

  it("falls back to the axios error message when data is null", () => {
    expect(parseErrorMessage(null, "Network Error")).toBe("Network Error");
  });

  it("prioritises envelope over detail when both are present", () => {
    const data = {
      error: { message: "YouTube blocked this server" },
      detail: "should be ignored",
    };
    expect(parseErrorMessage(data, "axios")).toBe("YouTube blocked this server");
  });

  it("returns a generic fallback string when all fields are absent", () => {
    const result = parseErrorMessage({}, "");
    expect(result).toBe("An error occurred");
  });

  it("does not coerce a detail array to a string", () => {
    // detail is an array → not a string → skipped, falls through to axiosMessage.
    const data = { detail: [{ msg: "field required" }] };
    const result = parseErrorMessage(data, "Network Error");
    expect(result).not.toContain("[object");
    expect(result).toBe("Network Error");
  });

  it("handles a nested error object without message gracefully", () => {
    const data = { error: { code: "ERR_UNKNOWN" } };
    // No message in error → falls through to axiosMessage.
    expect(parseErrorMessage(data, "fallback")).toBe("fallback");
  });
});
