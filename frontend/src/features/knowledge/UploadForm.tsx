/** Add a knowledge source — paste text or upload a .txt/.md file. Invalidates the source list
 * on success so the new row appears and polling picks it up. */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button, Card } from "../../components";
import { createPasteSource, createUrlSource, uploadFileSource } from "./api";

export function UploadForm() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");

  const invalidate = () => qc.invalidateQueries({ queryKey: ["kb", "sources"] });

  const pasteMut = useMutation({
    mutationFn: () => createPasteSource(name.trim(), content),
    onSuccess: () => {
      setName("");
      setContent("");
      invalidate();
    },
  });

  const fileMut = useMutation({
    mutationFn: () => uploadFileSource(file as File, name.trim() || undefined),
    onSuccess: () => {
      setName("");
      setFile(null);
      invalidate();
    },
  });

  const urlMut = useMutation({
    mutationFn: () => createUrlSource(name.trim(), url.trim()),
    onSuccess: () => {
      setName("");
      setUrl("");
      invalidate();
    },
  });

  return (
    <Card>
      <h3>Add a source</h3>
      <div style={{ display: "grid", gap: 12 }}>
        <input
          placeholder="Source name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          style={{ padding: 8 }}
        />

        <div style={{ display: "grid", gap: 6 }}>
          <label style={{ fontSize: 13, color: "#6b7280" }}>Paste text</label>
          <textarea
            rows={5}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            style={{ width: "100%", padding: 8 }}
          />
          <div>
            <Button
              disabled={!name.trim() || !content.trim() || pasteMut.isPending}
              onClick={() => pasteMut.mutate()}
            >
              {pasteMut.isPending ? "Uploading…" : "Add pasted text"}
            </Button>
          </div>
          {pasteMut.isError && <p role="alert">Upload failed — check the name and try again.</p>}
        </div>

        <div style={{ display: "grid", gap: 6 }}>
          <label style={{ fontSize: 13, color: "#6b7280" }}>Or upload a .txt / .md / .pdf / .docx file</label>
          <input
            type="file"
            accept=".txt,.md,.pdf,.docx,text/plain,text/markdown,application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <div>
            <Button
              variant="ghost"
              disabled={!file || fileMut.isPending}
              onClick={() => fileMut.mutate()}
            >
              {fileMut.isPending ? "Uploading…" : "Upload file"}
            </Button>
          </div>
          {fileMut.isError && <p role="alert">Upload failed — .txt / .md / .pdf / .docx only.</p>}
        </div>

        <div style={{ display: "grid", gap: 6 }}>
          <label style={{ fontSize: 13, color: "#6b7280" }}>Or crawl a URL</label>
          <input
            placeholder="https://example.com/help"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            style={{ padding: 8 }}
          />
          <div>
            <Button
              variant="ghost"
              disabled={!name.trim() || !url.trim() || urlMut.isPending}
              onClick={() => urlMut.mutate()}
            >
              {urlMut.isPending ? "Crawling…" : "Add URL"}
            </Button>
          </div>
          {urlMut.isError && <p role="alert">Crawl failed — check the URL.</p>}
        </div>
      </div>
    </Card>
  );
}
