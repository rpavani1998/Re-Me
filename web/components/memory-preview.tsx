"use client";
import {useState, type ReactNode} from "react";

export function MemoryPreview({url, children}: {url?: string | null; children?: ReactNode}) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  if (!url || failedUrl === url || !/^https?:\/\//i.test(url)) return <>{children}</>;
  // Direct loading avoids sending private saved URLs to an image proxy.
  // eslint-disable-next-line @next/next/no-img-element
  return <img className="memory-preview-image" src={url} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailedUrl(url)}/>;
}
