import { expect, it } from "vitest";
import { MAX_BROWSER_ARTIFACT_BYTES, uploadArtifact } from "../../src/features/activities/api";

it("rejects a large browser artifact before reading it into Mac memory", async () => {
  const file = new File(["small"], "too-large.pdf", { type: "application/pdf" });
  Object.defineProperty(file, "size", { value: MAX_BROWSER_ARTIFACT_BYTES + 1 });
  await expect(uploadArtifact(1, 1, file, "written_output")).rejects.toThrow("25 MB or smaller");
});
