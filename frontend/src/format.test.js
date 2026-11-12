import { describe, expect, it } from "vitest";
import { displayB, displayDifference, displayValue, nextOrdering } from "./format.js";

describe("displayValue", () => {
  it("formats decimal strings from the API", () => {
    expect(displayValue("125400.00")).toEqual({ text: "125,400.00", kind: "number" });
  });
  it("shows a dash for absent values instead of 0", () => {
    expect(displayValue(null).text).toBe("—");
  });
});

describe("displayB", () => {
  it("distinguishes blank from absent", () => {
    expect(displayB({ reason: "UNPARSEABLE_VALUE", b_value: null, b_raw_value: "" }).kind).toBe("blank");
    expect(displayB({ reason: "MISSING_IN_B", b_value: null, b_raw_value: "" }).kind).toBe("none");
  });
  it("shows the raw text when B sent something unparseable", () => {
    expect(displayB({ reason: "UNPARSEABLE_VALUE", b_value: null, b_raw_value: "abc" }).text).toBe('not a number: "abc"');
  });
});

describe("displayDifference", () => {
  it("is B minus A in exact cents, with a sign", () => {
    expect(displayDifference({ a_value: "79259.03", b_value: "61921.12" }).text).toBe("−17,337.91");
    expect(displayDifference({ a_value: "0.10", b_value: "0.30" }).text).toBe("+0.20");
    expect(displayDifference({ a_value: "5.00", b_value: "5.00" }).text).toBe("0.00");
  });
  it("is a dash when either side is missing", () => {
    expect(displayDifference({ a_value: null, b_value: "1.00" }).kind).toBe("none");
  });
});

describe("nextOrdering", () => {
  it("cycles high-to-low, low-to-high, off", () => {
    expect(nextOrdering("", "b_value")).toBe("-b_value");
    expect(nextOrdering("-b_value", "b_value")).toBe("b_value");
    expect(nextOrdering("b_value", "b_value")).toBe("");
    expect(nextOrdering("-a_value", "b_value")).toBe("-b_value");
  });
});
