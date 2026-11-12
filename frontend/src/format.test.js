import { describe, expect, it } from "vitest";
import { displayB, displayValue } from "./format.js";

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
