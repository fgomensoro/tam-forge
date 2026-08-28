import { useState } from "react";
import { uploadArtifact, type ArtifactReference } from "./api";

export function ArtifactUploader({ activityId, expectedVersion, disabled, onUploaded }: { activityId: number; expectedVersion: number; disabled: boolean; onUploaded: (reference: ArtifactReference, name: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const upload = async () => {
    if (!file) return;
    setBusy(true); setMessage(null);
    try {
      const artifact = await uploadArtifact(activityId, expectedVersion, file, "written_output");
      onUploaded({ artifact_id: artifact.id, link_role: "supporting" }, artifact.original_filename);
      setMessage(`${artifact.original_filename} uploaded`);
    } catch { setMessage("Upload failed. Your draft is unchanged."); }
    finally { setBusy(false); }
  };
  return (
    <section className="artifact-uploader" aria-labelledby="artifact-title">
      <h3 id="artifact-title">Supporting artifact <span>optional · documents up to 25 MB</span></h3>
      <div><input aria-label="Supporting artifact" type="file" accept=".md,.txt,.json,.csv,.sql,.pdf" disabled={disabled || busy} onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><button className="secondary-button" type="button" disabled={disabled || busy || !file} onClick={() => void upload()}>{busy ? "Uploading…" : "Upload"}</button></div>
      {message ? <p role="status">{message}</p> : null}
    </section>
  );
}
