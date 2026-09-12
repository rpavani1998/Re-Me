"use client";
import {MemoryPreview} from "./memory-preview";

type CardMemory = {
  title: string; summary: string; type: string; source_type?: string;
  source_url: string | null; image_url?: string | null; saved_excerpt?: string;
  possible_actions?: {type: string; label: string}[];
};

export function MemoryCard({memory: m, index, onOpen}: {memory: CardMemory; index: number; onOpen: () => void}) {
  let host = "";
  let tweet = false;
  const toDos = (m.possible_actions || []).filter(a => a.type !== "open").length;
  try {
    const url = new URL(m.source_url || "");
    host = url.hostname.replace(/^www\./, "");
    tweet = ["x.com", "twitter.com", "mobile.twitter.com"].includes(host) && /\/status\/\d+/.test(url.pathname);
  } catch { /* Thoughts have no source URL. */ }
  const image = m.source_type === "image" || m.type === "image";
  const quote = !image && !!m.saved_excerpt?.trim() && (m.source_type === "selection" || m.type === "quote" || tweet);
  const variant = image ? "image" : quote ? "quote" : host ? "link" : "note";
  return <button className={`memory-card mosaic-${variant} tone-${index % 5}`} onClick={onOpen} aria-label={`Open memory: ${m.title}`}>
    {image ? <MemoryPreview url={m.image_url}><div className="image-unavailable"><span>Image unavailable</span><strong>{m.title}</strong></div></MemoryPreview> : quote ?
      <div className="quote-content"><span className="quote-mark" aria-hidden="true">“</span><blockquote>{m.saved_excerpt}</blockquote><span className="quote-source">{tweet ? "Saved from " : "A passage from "}{host || m.title}</span></div> : <>
        {m.image_url && <MemoryPreview url={m.image_url}/>}
        <div className="mosaic-copy"><span className="mosaic-source">{host || "A thought to keep"}</span><h3>{m.title}</h3><p>{m.summary}</p>{toDos > 0 && <span className="action-chip">✧ {toDos} thing{toDos === 1 ? "" : "s"} to do</span>}</div>
      </>}
  </button>;
}
