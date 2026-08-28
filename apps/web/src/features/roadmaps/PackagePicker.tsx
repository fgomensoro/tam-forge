import type { ChangeEvent } from "react";
import type { RoadmapPackage } from "./api";

export function relativeFolderFiles(files: File[]) {
  const entries = files.map((file) => ({
    file,
    path: file.webkitRelativePath || file.name,
  }));
  const firstSegments = new Set(entries.map(({ path }) => path.split("/")[0]));
  if (firstSegments.size !== 1 || !entries.every(({ path }) => path.includes("/"))) return entries;
  return entries.map(({ file, path }) => ({ file, path: path.slice(path.indexOf("/") + 1) }));
}

export function PackagePicker({
  selection,
  disabled,
  onSelect,
}: {
  selection: RoadmapPackage | null;
  disabled: boolean;
  onSelect: (selection: RoadmapPackage) => void;
}) {
  const selectZip = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) onSelect({ kind: "zip", file });
  };
  const selectFolder = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    if (files.length) onSelect({ kind: "folder_entries", files: relativeFolderFiles(files) });
  };
  const selectedLabel = selection?.kind === "zip"
    ? selection.file.name
    : selection
      ? `${selection.files.length} files selected`
      : "No package selected";

  return (
    <fieldset className="package-picker" disabled={disabled}>
      <legend>Choose an exported roadmap package</legend>
      <p className="field-help">TAM Forge never reads your Obsidian vault directly. Export a ZIP or choose the roadmap folder in your browser.</p>
      <div className="picker-options">
        <label className="file-option">
          <span>ZIP package</span>
          <input type="file" accept=".zip,application/zip" aria-label="Roadmap ZIP" onChange={selectZip} />
        </label>
        <span className="option-divider">or</span>
        <label className="file-option">
          <span>Browser folder</span>
          <input
            type="file"
            aria-label="Roadmap folder"
            multiple
            {...{ webkitdirectory: "", directory: "" }}
            onChange={selectFolder}
          />
        </label>
      </div>
      <p className="selection-name" aria-live="polite">{selectedLabel}</p>
    </fieldset>
  );
}
